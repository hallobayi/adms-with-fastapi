"""Kompatibilitas mundur.

Logika koneksi sudah dipindah ke `app.database`. Modul ini dipertahankan
agar kode lama yang memanggil `db.connect()` tidak langsung rusak.
Sebaiknya impor dari `app.database` pada kode baru.
"""

from __future__ import annotations

from app.database import connection, get_connection, ping

__all__ = ["connect", "connection", "get_connection", "ping"]


def connect():
    """Ambil satu koneksi MySQL dari pool.

    Catatan: berbeda dengan versi lama, pemanggil bertanggung jawab
    menutup koneksi (`conn.close()`). Lebih disarankan memakai
    `app.database.connection()` sebagai context manager.
    """
    return get_connection()
