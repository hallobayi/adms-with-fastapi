"""Penyimpanan sederhana di memori.

Sementara ini dipakai sebagai contoh sebelum data benar-benar dibaca dari
MySQL. Rute HTTP tidak boleh menyentuh struktur data secara langsung —
semua lewat fungsi di modul ini agar mudah diganti dengan kueri database.
"""

from __future__ import annotations

_ITEMS: dict[str, str] = {"foo": "The Foo Wrestless"}


def list_items() -> dict[str, str]:
    """Kembalikan salinan seluruh item."""
    return dict(_ITEMS)


def get_item(item_id: str) -> str | None:
    """Ambil satu item, atau `None` bila tidak ada."""
    return _ITEMS.get(item_id)
