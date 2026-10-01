"""Lapisan akses database.

Modul ini bertanggung jawab atas dua hal: menyediakan koneksi MySQL, dan
menjembatani koneksi blocking itu ke endpoint `async`. Kueri bisnis tetap
tinggal di modul `queries_*` / `store` masing-masing.

**Kenapa jembatannya ada di sini, bukan di tiap router.** `mysql-connector`
tidak punya API async. Endpoint `/iclock/*` dan `/api/admin/*` ditulis `async`,
jadi memanggil driver langsung akan menahan event loop selama kueri berjalan —
satu batch besar milik satu device menunda semua device lain. Pola
"buka koneksi → jalankan → commit" karena itu diulang di hampir setiap endpoint;
sebelum `fetch()`/`execute()` ada, pola itu disalin-tempel lebih dari 30 kali
(berikut sembilan salinan identik `_run_blocking`), dan setiap salinan adalah
kesempatan untuk lupa `commit`, lupa `rollback`, atau lupa menutup koneksi.

Dua helper di bawah membagi pola itu menurut niatnya — dan nama fungsinya
langsung memberi tahu pembaca apakah sebuah endpoint mengubah data:

- `fetch(...)`  — baca saja.
- `execute(...)` — menulis; commit bila sukses, rollback bila gagal.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import partial
from typing import Any, TypeVar

import anyio.to_thread
import mysql.connector
from mysql.connector import MySQLConnection
from mysql.connector import pooling

from app.config import get_settings

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Pool dibuat malas (lazy) supaya proses import modul tidak langsung mencoba
# menyambung ke database — penting agar unit test bisa berjalan tanpa MySQL.
_pool: pooling.MySQLConnectionPool | None = None

#: Ukuran pool. Handler `/iclock/*` menjalankan pekerjaan database di worker
#: thread (lihat `app/iclock/router.py`), jadi pool inilah yang membatasi
#: berapa banyak device bisa dilayani bersamaan. Nilai kecil membuat device
#: mengantre menunggu koneksi; ambil dari environment supaya bisa dinaikkan
#: tanpa mengubah kode saat jumlah device bertambah.
_DEFAULT_POOL_SIZE = 10


def _get_pool() -> pooling.MySQLConnectionPool:
    global _pool
    if _pool is None:
        settings = get_settings()
        logger.info("Membuat connection pool ke %s", settings.database.host)
        _pool = pooling.MySQLConnectionPool(
            pool_name="adms_pool",
            pool_size=settings.database.pool_size,
            **settings.database.as_kwargs(),
        )
    return _pool


def get_connection() -> MySQLConnection:
    """Ambil satu koneksi dari pool."""
    return _get_pool().get_connection()


@contextmanager
def connection() -> Iterator[MySQLConnection]:
    """Context manager koneksi: selalu menutup koneksi walau terjadi error.

    Pemakaian:
        with connection() as conn:
            with conn.cursor(dictionary=True) as cur:
                cur.execute("SELECT 1")
    """
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


# --- Jembatan async untuk koneksi blocking --------------------------------


async def run_in_thread(func: Callable[..., T], /, **kwargs: Any) -> T:
    """Jalankan fungsi blocking di worker thread dan kembalikan hasilnya.

    Dipakai untuk pekerjaan blocking yang **tidak** memakai koneksi — mis.
    `ping()` — atau untuk kasus yang butuh kendali transaksi sendiri (beberapa
    kueri dalam satu koneksi, commit bersyarat). Untuk kasus satu-kueri yang
    biasa, pakai `fetch()` atau `execute()` yang sudah menangani koneksi.

    `anyio.to_thread.run_sync` (yang dipakai Starlette sendiri di balik layar)
    memindahkan pekerjaan ke worker thread sehingga event loop tetap melayani
    request lain selama menunggu MySQL. Exception dari worker tetap diteruskan
    ke pemanggil — handler iClock mengandalkannya untuk jalur penyelamatan.
    """
    return await anyio.to_thread.run_sync(partial(func, **kwargs))


async def fetch(func: Callable[..., T], /, **kwargs: Any) -> T:
    """Jalankan kueri **baca** di worker thread.

    Membuka satu koneksi, memanggil `func(conn, **kwargs)`, lalu menutupnya.
    Tidak ada `commit()`: fungsi baca tidak mengubah data, dan menutup koneksi
    sudah mengembalikannya ke pool. Memakai `fetch` (bukan `execute`) untuk
    sebuah penulisan akan membuat perubahan **diam-diam hilang** — karena itu
    bedakan keduanya dengan jelas di titik pemanggilan.
    """

    def _work() -> T:
        with connection() as conn:
            return func(conn, **kwargs)

    return await run_in_thread(_work)


async def execute(func: Callable[..., T], /, **kwargs: Any) -> T:
    """Jalankan kueri **tulis** di worker thread, dengan transaksi otomatis.

    `commit()` dijalankan hanya bila `func` selesai tanpa error. Bila ia
    melempar — termasuk `HTTPException` hasil pemetaan galat MySQL seperti
    duplikat UNIQUE (1062) — transaksi di-`rollback` lebih dulu, lalu error
    diteruskan apa adanya supaya pemanggil tetap bisa mengubahnya menjadi
    respons HTTP yang tepat.
    """

    def _work() -> T:
        with connection() as conn:
            try:
                result = func(conn, **kwargs)
            except Exception:
                conn.rollback()
                raise
            conn.commit()
            return result

    return await run_in_thread(_work)


def ping() -> bool:
    """Cek apakah database masih bisa dihubungi."""
    try:
        with connection() as conn:
            conn.ping(reconnect=True, attempts=1, delay=0)
        return True
    except mysql.connector.Error:
        logger.exception("Ping database gagal")
        return False
