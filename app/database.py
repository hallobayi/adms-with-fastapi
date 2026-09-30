"""Lapisan akses database.

Modul ini hanya bertanggung jawab menyediakan koneksi MySQL. Kueri bisnis
tidak ditulis di sini agar tetap terpisah dari konfigurasi koneksi.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

import mysql.connector
from mysql.connector import MySQLConnection
from mysql.connector import pooling

from app.config import get_settings

logger = logging.getLogger(__name__)

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


def ping() -> bool:
    """Cek apakah database masih bisa dihubungi."""
    try:
        with connection() as conn:
            conn.ping(reconnect=True, attempts=1, delay=0)
        return True
    except mysql.connector.Error:
        logger.exception("Ping database gagal")
        return False
