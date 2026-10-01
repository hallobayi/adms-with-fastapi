"""Helper kecil yang dipakai bersama router CRUD data master `/api/admin/*`.

Dikumpulkan di sini supaya tidak disalin ke tiap modul router. Isinya dua
macam pekerjaan yang sama-sama "menerjemahkan dunia MySQL ke dunia HTTP":

- `duplicate_error` — mengubah galat UNIQUE MySQL menjadi 409 yang bisa dibaca.
- `time_str` / `work_days_list` — menormalkan tipe kolom MySQL (`TIME`, `SET`)
  menjadi bentuk yang stabil dan ramah JSON.

`work_days_list` khususnya menutup bug nyata: `mysql-connector` mengembalikan
kolom `SET` sebagai `set` Python, dan `str(set)` pernah lolos ke respons API
sebagai `"{'MO', 'TU'}"` (lihat readme).
"""

from __future__ import annotations

from datetime import timedelta

import mysql.connector
from fastapi import HTTPException, status

from app.admin.queries_master import WORK_DAY_ORDER


def duplicate_error(exc: mysql.connector.Error, message: str) -> HTTPException | None:
    """Terjemahkan galat UNIQUE MySQL (1062) menjadi 409 yang bisa dibaca.

    Mengembalikan `None` bila errornya bukan duplikat — pemanggil yang
    memutuskan untuk meneruskannya. (Bentuk ini, bukan `raise` langsung, supaya
    pemanggil bisa membungkusnya dengan `raise ... from exc` agar rantai
    penyebabnya tetap utuh di traceback.)
    """
    if exc.errno == 1062:
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message)
    return None


def time_str(value: object) -> str:
    """Normalisasi `TIME` MySQL (datetime.timedelta) menjadi 'HH:MM:SS'."""
    if isinstance(value, timedelta):
        total = int(value.total_seconds())
        return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"
    return str(value)


def work_days_list(value: object) -> list[str]:
    """Ubah kolom `SET` MySQL menjadi daftar hari yang terurut kanonik.

    `mysql-connector` mengembalikan kolom `SET` sebagai `set` Python, bukan
    string. `str(set)` menghasilkan `"{'MO', 'TU'}"` — dan itu pernah lolos ke
    respons API. Di sini dikembalikan ke urutan kanonik supaya klien selalu
    menerima daftar yang sama untuk isi yang sama.
    """
    if value is None:
        return []
    if isinstance(value, (set, frozenset, list, tuple)):
        raw = {str(v).strip().upper() for v in value}
    else:
        raw = {part.strip().upper() for part in str(value).split(",")}
    return [day for day in WORK_DAY_ORDER if day in raw]


__all__ = ["duplicate_error", "time_str", "work_days_list"]
