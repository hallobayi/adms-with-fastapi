"""Endpoint CRUD shift `/api/admin/shifts*`.

Jam kerja yang dipakai untuk menghitung keterlambatan. `start_time`/`end_time`
adalah **jam dinding setempat**, bukan UTC — lihat SCHEMA §16.
"""

from __future__ import annotations

import logging

import mysql.connector
from fastapi import APIRouter, Depends, HTTPException, status

from app.admin import auth, queries_master, schemas
from app.admin.dependencies import current_admin
from app.admin.helpers import duplicate_error, time_str
from app.database import execute, fetch

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/shifts", tags=["admin:shifts"])


def _shift_out(row: dict[str, object]) -> schemas.ShiftOut:
    return schemas.ShiftOut(
        id=int(row["id"]),
        name=row["name"],
        start_time=time_str(row["start_time"]),
        end_time=time_str(row["end_time"]),
        late_tolerance_min=int(row.get("late_tolerance_min") or 0),
        early_leave_tol_min=int(row.get("early_leave_tol_min") or 0),
        is_overnight=bool(row.get("is_overnight")),
        is_active=bool(row.get("is_active")),
    )


@router.get("", response_model=schemas.ShiftListResponse)
async def list_shifts(
    is_active: bool | None = None,
    _: auth.AdminUser = Depends(current_admin),
) -> schemas.ShiftListResponse:
    rows = await fetch(queries_master.list_shifts, is_active=is_active)
    return schemas.ShiftListResponse(total=len(rows), shifts=[_shift_out(r) for r in rows])


@router.get("/{shift_id}", response_model=schemas.ShiftOut)
async def get_shift(
    shift_id: int, _: auth.AdminUser = Depends(current_admin)
) -> schemas.ShiftOut:
    row = await fetch(queries_master.get_shift, shift_id=shift_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Shift tidak ditemukan."
        )
    return _shift_out(row)


@router.post("", response_model=schemas.ShiftOut, status_code=status.HTTP_201_CREATED)
async def create_shift(
    payload: schemas.ShiftCreateRequest,
    admin: auth.AdminUser = Depends(current_admin),
) -> schemas.ShiftOut:
    fields = payload.model_dump()

    def _create(conn) -> int:
        try:
            return queries_master.create_shift(conn, **fields)
        except mysql.connector.Error as exc:
            mapped = duplicate_error(exc, f"Nama shift {payload.name!r} sudah dipakai.")
            if mapped:
                raise mapped from exc
            raise

    shift_id = await execute(_create)
    logger.info("Shift %s (%s) dibuat oleh admin %r", shift_id, payload.name, admin.username)

    row = await fetch(queries_master.get_shift, shift_id=shift_id)
    return _shift_out(row)


@router.patch("/{shift_id}", response_model=schemas.ShiftOut)
async def update_shift(
    shift_id: int,
    payload: schemas.ShiftUpdateRequest,
    admin: auth.AdminUser = Depends(current_admin),
) -> schemas.ShiftOut:
    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Tidak ada field yang diubah."
        )

    def _update(conn) -> bool:
        try:
            return queries_master.update_shift(conn, shift_id, **fields)
        except mysql.connector.Error as exc:
            mapped = duplicate_error(exc, "Nama shift sudah dipakai.")
            if mapped:
                raise mapped from exc
            raise

    changed = await execute(_update)
    if not changed:
        if await fetch(queries_master.get_shift, shift_id=shift_id) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Shift tidak ditemukan."
            )

    logger.info("Shift %s diperbarui oleh admin %r: %s", shift_id, admin.username, sorted(fields))

    row = await fetch(queries_master.get_shift, shift_id=shift_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Shift tidak ditemukan."
        )
    return _shift_out(row)


@router.delete("/{shift_id}", response_model=schemas.MessageResponse)
async def delete_shift(
    shift_id: int, admin: auth.AdminUser = Depends(current_admin)
) -> schemas.MessageResponse:
    """Hapus shift. Ditolak 409 bila masih dipakai penugasan."""
    ok, message = await execute(queries_master.delete_shift, shift_id=shift_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message)

    logger.info("Shift %s dihapus oleh admin %r", shift_id, admin.username)
    return schemas.MessageResponse(message=message, id=shift_id)
