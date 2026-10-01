"""Endpoint hari libur `/api/admin/holidays*`.

`is_recurring = 1` berarti tanggalnya diulang setiap tahun (mis. 17 Agustus,
bukan hari raya yang bergeser seperti Idul Fitri — untuk yang bergeser,
tambahkan per tahun).
"""

from __future__ import annotations

import logging
from datetime import date

import mysql.connector
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.admin import auth, queries_master, schemas
from app.admin.dependencies import current_admin
from app.admin.helpers import duplicate_error
from app.database import execute, fetch

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/holidays", tags=["admin:holidays"])


def _holiday_out(row: dict[str, object]) -> schemas.HolidayOut:
    hd = row["holiday_date"]
    return schemas.HolidayOut(
        id=int(row["id"]),
        holiday_date=hd.isoformat() if isinstance(hd, date) else str(hd),
        name=row["name"],
        is_recurring=bool(row.get("is_recurring")),
    )


def _find_holiday(conn, *, holiday_id: int) -> dict[str, object] | None:
    """Ambil satu hari libur berdasarkan id.

    Belum ada kueri `get_holiday` khusus, jadi penyaringan dilakukan di sini —
    daftar hari libur selalu kecil (ratusan baris per tahun).
    """
    _, rows = queries_master.list_holidays(conn, limit=500)
    return next((r for r in rows if int(r["id"]) == holiday_id), None)


@router.get("", response_model=schemas.HolidayListResponse)
async def list_holidays(
    year: int | None = None,
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: auth.AdminUser = Depends(current_admin),
) -> schemas.HolidayListResponse:
    total, rows = await fetch(
        queries_master.list_holidays, year=year, limit=limit, offset=offset
    )
    return schemas.HolidayListResponse(
        total=total, holidays=[_holiday_out(r) for r in rows]
    )


@router.post(
    "", response_model=schemas.HolidayOut, status_code=status.HTTP_201_CREATED
)
async def create_holiday(
    payload: schemas.HolidayCreateRequest,
    admin: auth.AdminUser = Depends(current_admin),
) -> schemas.HolidayOut:
    """Tambah hari libur."""
    fields = payload.model_dump()

    def _create(conn) -> int:
        try:
            return queries_master.create_holiday(conn, **fields)
        except mysql.connector.Error as exc:
            mapped = duplicate_error(
                exc, f"Hari libur pada {payload.holiday_date} sudah ada."
            )
            if mapped:
                raise mapped from exc
            raise

    holiday_id = await execute(_create)
    logger.info(
        "Hari libur %s (%s) ditambahkan oleh admin %r",
        holiday_id, payload.holiday_date, admin.username,
    )

    row = await fetch(_find_holiday, holiday_id=holiday_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Hari libur dibuat tetapi gagal dibaca kembali.",
        )
    return _holiday_out(row)


@router.delete("/{holiday_id}", response_model=schemas.MessageResponse)
async def delete_holiday(
    holiday_id: int, admin: auth.AdminUser = Depends(current_admin)
) -> schemas.MessageResponse:
    ok = await execute(queries_master.delete_holiday, holiday_id=holiday_id)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Hari libur tidak ditemukan."
        )

    logger.info("Hari libur %s dihapus oleh admin %r", holiday_id, admin.username)
    return schemas.MessageResponse(message="Hari libur dihapus.", id=holiday_id)
