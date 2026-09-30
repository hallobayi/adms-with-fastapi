"""Uji sifat yang menjaga performa jalur ingest tetap benar.

Dua hal yang diuji di sini bukan tentang *hasil*, melainkan tentang *cara*:

1. **Event loop tidak boleh diblokir oleh I/O database.** Endpoint `/iclock/*`
   `async` tetapi `mysql-connector` blocking. Kalau pekerjaan itu dijalankan
   langsung, satu batch besar milik satu device menunda semua device lain.
   Uji ini membuktikan pekerjaan benar-benar pindah ke thread lain.
2. **Pemisahan baris dipakai konsisten.** Body dipisah sekali per request,
   dan varian `*_lines` harus memberi hasil yang identik dengan varian muatan.
"""

from __future__ import annotations

import threading
import time

import anyio
import pytest

from app.iclock import parser
from app.iclock.router import _run_blocking


# --- Pekerjaan blocking benar-benar pindah ke thread lain ------------------


def test_run_blocking_tidak_menjalankan_di_thread_event_loop() -> None:
    """Fungsi harus dijalankan di thread yang BERBEDA dari pemanggil.

    Inilah inti perbaikan: bila `_run_blocking` hanya memanggil fungsinya
    langsung, `threading.get_ident()` akan sama dan event loop tetap diblokir.
    """
    caller_thread = threading.get_ident()
    seen: dict[str, int] = {}

    def blocking() -> None:
        seen["thread"] = threading.get_ident()

    anyio.run(_run_blocking, blocking)

    assert seen["thread"] != caller_thread, (
        "pekerjaan blocking masih berjalan di thread event loop"
    )


def test_run_blocking_meneruskan_kwargs_dan_nilai_kembalian() -> None:
    """Pembungkus harus transparan: argumen keyword dan hasil tetap utuh."""

    def add(*, a: int, b: int) -> int:
        return a + b

    # `anyio.run` tidak meneruskan kwargs, jadi dibungkus lambda.
    result = anyio.run(lambda: _run_blocking(add, a=2, b=3))

    assert result == 5


def test_run_blocking_melewatkan_exception() -> None:
    """Kegagalan di worker thread harus tetap terlihat pemanggil.

    Handler iClock punya blok `except` sendiri untuk mengarsipkan body saat
    gagal; kalau exception di sini ditelan, jalur penyelamatan itu tidak akan
    pernah tercapai.
    """

    def boom() -> None:
        raise RuntimeError("gagal")

    with pytest.raises(RuntimeError, match="gagal"):
        anyio.run(_run_blocking, boom)


def test_pekerjaan_blocking_berjalan_bersamaan_bukan_berurutan() -> None:
    """Dua pemanggilan paralel tidak boleh saling menunggu.

    Kalau keduanya berbagi event loop yang sama dan dijalankan langsung,
    total waktunya ~2× durasi satu pekerjaan. Di worker thread yang terpisah,
    keduanya tumpang tindih dan totalnya mendekati 1×.
    """
    delay = 0.3
    started = threading.Barrier(2, timeout=5)

    def slow() -> None:
        # Kedua thread harus benar-benar berjalan pada saat yang sama.
        started.wait()
        time.sleep(delay)

    async def run_both() -> None:
        async with anyio.create_task_group() as tg:
            tg.start_soon(_run_blocking, slow)
            tg.start_soon(_run_blocking, slow)

    began = time.perf_counter()
    anyio.run(run_both)
    elapsed = time.perf_counter() - began

    assert elapsed < delay * 2, (
        f"pekerjaan tampak berurutan ({elapsed:.2f}s untuk 2×{delay}s) — "
        "kemungkinan berjalan di event loop yang sama"
    )


# --- Varian *_lines sepakat dengan varian muatan ---------------------------


ATTLOG = "\r\n".join(
    [
        "0012\t2026-09-29 08:15:03\t0\t1\t0",
        "0013\t2026-09-29 09:00:00\t1\t1\t0\t999",
        "rusak",
        "0014\t2026-09-29 17:30:00\t1\t4\t0",
    ]
)

OPERLOG = "\r\n".join(
    [
        "USER\tPIN=0012\tName=Budi Santoso\tPri=0",
        "FP\tPIN=0012\tFID=0\tSize=4\tValid=1\tTMP=AAAA",
        "BIODATA\tPin=0013\tNo=1\tType=1\tTmp=BBBB",
        "BIODATA\tPin=0013\tNo=50\tType=3\tTmp=CCCC",
    ]
)


def test_parse_attendance_lines_sama_dengan_parse_attendance() -> None:
    """Jalur ingest memakai `_lines`; hasilnya harus identik.

    Kalau kedua jalur berbeda, body yang diarsipkan dan data yang tersimpan
    akan menjelaskan hal yang tidak sama.
    """
    from_payload = parser.parse_attendance(ATTLOG)
    from_lines = parser.parse_attendance_lines(parser.split_lines(ATTLOG))

    assert from_payload == from_lines
    assert len(from_lines) == 3, "baris rusak harus dilewati, bukan menggagalkan batch"


def test_parse_fingerprint_lines_sama_dengan_parse_fingerprints() -> None:
    from_payload = parser.parse_fingerprints(OPERLOG)
    from_lines = parser.parse_fingerprint_lines(parser.split_lines(OPERLOG))

    assert from_payload == from_lines
    # BIODATA Type=3 (bukan jari) harus tetap tersaring di kedua jalur.
    assert len(from_lines) == 2


def test_parse_users_lines_sama_dengan_parse_users() -> None:
    from_payload = parser.parse_users(OPERLOG)
    from_lines = parser.parse_users_lines(parser.split_lines(OPERLOG))

    assert from_payload == from_lines
    assert len(from_lines) == 1


def test_split_lines_membuang_baris_kosong_tanpa_memangkas_isi() -> None:
    """Perilaku lama harus dipertahankan persis.

    `split_lines` dipanggil tiga kali per request sebelum dirapikan, jadi
    menggantinya harus tidak mengubah arti satu baris pun.
    """
    payload = "a\tb \r\n\r\n\r c \n\n\n d\re"
    assert parser.split_lines(payload) == ["a\tb", "c", "d", "e"]


def test_split_lines_menghitung_baris_yang_dikirim_device() -> None:
    """Jumlah baris inilah yang dibalas `OK: <n>` ke device.

    Angka yang lebih kecil dari yang dikirim membuat device mengirim ulang
    batch yang sama selamanya — jadi tidak boleh ada baris yang hilang.
    """
    body = "\r\n".join(f"{i:04d}\t2026-09-29 08:15:03\t0\t1\t0" for i in range(500))
    assert len(parser.split_lines(body)) == 500

    # Termasuk saat body memakai LF saja, atau diakhiri pemisah.
    assert len(parser.split_lines(body.replace("\r\n", "\n") + "\r\n")) == 500
