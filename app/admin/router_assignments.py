"""Endpoint penugasan shift `/api/admin/shift-assignments*`.

Menjawab "siapa masuk shift apa, berlaku sejak kapan". `effective_from` +
`shift_id` unik per karyawan di level database, jadi penugasan ganda pada
tanggal mulai yang sama ditolak database — bukan hanya oleh validasi aplikasi.
"""

from __future__ import annotations

import logging
from datetime import date

import mysql.connector
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.admin import auth, queries_master, schemas
from app.admin.dependencies import current_admin
from app.admin.helpers import work_days_list
from app.database import execute, fetch

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/shift-assignments", tags=["admin:shifts"])


def _assignment_out(row: dict[str, object]) -> schemas.ShiftAssignmentOut:
    from_d = row["effective_from"]
    to_d = row.get("effective_to")
    return schemas.ShiftAssignmentOut(
        id=int(row["id"]),
        employee_id=int(row["employee_id"]),
        pin=row.get("pin"),
        employee_name=row.get("employee_name"),
        shift_id=int(row["shift_id"]),
        shift_name=row.get("shift_name"),
        effective_from=from_d.isoformat() if isinstance(from_d, date) else str(from_d),
        effective_to=(
            to_d.isoformat() if isinstance(to_d, date) else (str(to_d) if to_d else None)
        ),
        work_days=work_days_list(row.get("work_days")),
    )


@router.get("", response_model=schemas.ShiftAssignmentListResponse)
async def list_assignments(
    employee_id: int | None = None,
    shift_id: int | None = None,
    active_on: date | None = None,
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: auth.AdminUser = Depends(current_admin),
) -> schemas.ShiftAssignmentListResponse:
    total, rows = await fetch(
        queries_master.list_shift_assignments,
        employee_id=employee_id,
        shift_id=shift_id,
        active_on=active_on,
        limit=limit,
        offset=offset,
    )
    return schemas.ShiftAssignmentListResponse(
        total=total, assignments=[_assignment_out(r) for r in rows]
    )


@router.post(
    "", response_model=schemas.MessageResponse, status_code=status.HTTP_201_CREATED
)
async def create_assignment(
    payload: schemas.ShiftAssignmentCreateRequest,
    admin: auth.AdminUser = Depends(current_admin),
) -> schemas.MessageResponse:
    """Tugaskan shift ke karyawan.

    `effective_from` + `shift_id` unik per karyawan di level database, jadi
    penugasan ganda pada tanggal mulai yang sama ditolak database — bukan hanya
    oleh validasi aplikasi.
    """
    if payload.effective_to is not None and payload.effective_to < payload.effective_from:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="`effective_to` tidak boleh lebih awal dari `effective_from`.",
        )

    fields = payload.model_dump()

    def _create(conn) -> int:
        try:
            return queries_master.create_shift_assignment(conn, **fields)
        except mysql.connector.Error as exc:
            # 1062 = duplikat, 1452 = FK gagal (karyawan/shift tidak ada).
            if exc.errno in (1062, 1452):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "Karyawan atau shift tidak ada, atau sudah punya penugasan "
                        "dengan tanggal mulai yang sama."
                    ),
                ) from exc
            raise

    assignment_id = await execute(_create)
    logger.info(
        "Penugasan shift %s dibuat oleh admin %r (karyawan=%s shift=%s)",
        assignment_id, admin.username, payload.employee_id, payload.shift_id,
    )
    return schemas.MessageResponse(message="Penugasan dibuat.", id=assignment_id)


@router.delete("/{assignment_id}", response_model=schemas.MessageResponse)
async def delete_assignment(
    assignment_id: int, admin: auth.AdminUser = Depends(current_admin)
) -> schemas.MessageResponse:
    ok = await execute(
        queries_master.delete_shift_assignment, assignment_id=assignment_id
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Penugasan tidak ditemukan."
        )

    logger.info("Penugasan %s dihapus oleh admin %r", assignment_id, admin.username)
    return schemas.MessageResponse(message="Penugasan dihapus.", id=assignment_id)
