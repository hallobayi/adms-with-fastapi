"""Endpoint rekap kehadiran `/api/admin/attendance*`.

Titik paling sensitif di modul ini adalah **`is_manual`**. Punch dari device
adalah data mentah dan tidak boleh diubah; koreksi manusia juga tidak boleh
hilang. Karena itu ada dua endpoint tulis yang sengaja dipisah:

- `PATCH /{id}` — koreksi manual, selalu menandai baris `is_manual = 1`.
- `POST /recompute` — olah ulang otomatis, yang **melewati** baris manual dan
  melaporkan berapa yang dilewatinya.
"""

from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.admin import auth, queries_attendance, schemas
from app.admin.dependencies import current_admin
from app.database import execute, fetch

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/attendance", tags=["admin:attendance"])


def _attendance_out(row: dict[str, object]) -> schemas.DailyAttendanceOut:
    work_date = row["work_date"]
    return schemas.DailyAttendanceOut(
        id=int(row["id"]),
        employee_id=int(row["employee_id"]),
        pin=row.get("pin"),
        employee_name=row.get("employee_name"),
        work_date=work_date.isoformat() if isinstance(work_date, date) else str(work_date),
        shift_id=row.get("shift_id"),
        shift_name=row.get("shift_name"),
        first_in=schemas._iso(row.get("first_in")),
        last_out=schemas._iso(row.get("last_out")),
        punch_count=int(row.get("punch_count") or 0),
        late_minutes=int(row.get("late_minutes") or 0),
        early_leave_minutes=int(row.get("early_leave_minutes") or 0),
        overtime_minutes=int(row.get("overtime_minutes") or 0),
        worked_minutes=(
            int(row["worked_minutes"]) if row.get("worked_minutes") is not None else None
        ),
        status=row["status"],
        is_manual=bool(row.get("is_manual")),
        note=row.get("note"),
    )


@router.get("", response_model=schemas.DailyAttendanceListResponse)
async def list_attendance(
    work_date: date | None = Query(
        default=None, description="Tanggal tunggal; mengabaikan date_from/date_to."
    ),
    date_from: date | None = None,
    date_to: date | None = None,
    employee_id: int | None = None,
    department: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    only_manual: bool = Query(
        default=False, description="Tampilkan hanya baris yang dikoreksi manual."
    ),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: auth.AdminUser = Depends(current_admin),
) -> schemas.DailyAttendanceListResponse:
    """Rekap kehadiran harian untuk rentang tanggal atau satu tanggal.

    `summary` dihitung atas **seluruh hasil filter**, bukan hanya halaman yang
    dikembalikan — angka "berapa yang telat" akan menyesatkan bila hanya
    mencakup 100 baris pertama.
    """
    total, summary, rows = await fetch(
        queries_attendance.list_daily_attendance,
        work_date=work_date,
        date_from=date_from,
        date_to=date_to,
        employee_id=employee_id,
        department=department,
        status=status_filter,
        only_manual=only_manual,
        limit=limit,
        offset=offset,
    )
    return schemas.DailyAttendanceListResponse(
        total=total, summary=summary, attendance=[_attendance_out(r) for r in rows]
    )


@router.get("/summary")
async def attendance_summary(
    days: int = Query(default=1, ge=1, le=90),
    _: auth.AdminUser = Depends(current_admin),
) -> dict[str, int]:
    """Ringkasan cepat `days` hari terakhir untuk kepala dashboard."""
    return await fetch(queries_attendance.attendance_summary, days=days)


@router.patch("/{attendance_id}", response_model=schemas.MessageResponse)
async def correct_attendance(
    attendance_id: int,
    payload: schemas.AttendanceCorrectRequest,
    admin: auth.AdminUser = Depends(current_admin),
) -> schemas.MessageResponse:
    """Koreksi manual satu baris rekap.

    `is_manual` **tidak** bisa dikirim klien: server selalu menyetelnya 1.
    Kalau tidak, koreksi ini akan dihapus job olah-ulang berikutnya dan admin
    akan menyaksikan perubahannya "kembali sendiri" tanpa penjelasan.
    """
    provided = payload.model_dump(exclude_unset=True)
    if not provided:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tidak ada field yang diubah.",
        )

    ok = await execute(
        queries_attendance.correct_daily_attendance,
        attendance_id=attendance_id,
        status=payload.status,
        first_in=payload.first_in,
        last_out=payload.last_out,
        late_minutes=payload.late_minutes,
        early_leave_minutes=payload.early_leave_minutes,
        overtime_minutes=payload.overtime_minutes,
        note=payload.note,
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Baris kehadiran tidak ditemukan.",
        )

    logger.info(
        "Baris kehadiran %s dikoreksi manual oleh admin %r: %s",
        attendance_id, admin.username, ", ".join(sorted(provided)),
    )
    return schemas.MessageResponse(
        message="Koreksi disimpan dan ditandai manual.", id=attendance_id
    )


@router.delete("/{attendance_id}", response_model=schemas.MessageResponse)
async def delete_attendance(
    attendance_id: int,
    admin: auth.AdminUser = Depends(current_admin),
) -> schemas.MessageResponse:
    """Hapus satu baris rekap (mis. terbentuk keliru).

    Punch mentah di `attendance_log` **tidak** ikut terhapus; olah ulang
    kapan pun akan membentuknya kembali dari data asli device.
    """
    ok = await execute(
        queries_attendance.delete_daily_attendance, attendance_id=attendance_id
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Baris kehadiran tidak ditemukan.",
        )

    logger.info("Baris kehadiran %s dihapus oleh admin %r", attendance_id, admin.username)
    return schemas.MessageResponse(message="Baris rekap dihapus.", id=attendance_id)


@router.post("/recompute", response_model=schemas.RecomputeResponse)
async def recompute(
    work_date: date,
    employee_id: int | None = None,
    overwrite_manual: bool = Query(
        default=False,
        description=(
            "Bila true, koreksi manual ikut ditimpa hasil hitungan. "
            "Hanya dipakai bila data punch sendiri sudah diperbaiki."
        ),
    ),
    admin: auth.AdminUser = Depends(current_admin),
) -> schemas.RecomputeResponse:
    """Olah ulang rekap satu tanggal dari punch mentah.

    Punch dikelompokkan memakai `punch_date` (tanggal **lokal** device), bukan
    UTC — memakai UTC akan menempatkan punch pagi pada hari kerja yang salah.
    """
    stats = await execute(
        queries_attendance.recompute_daily,
        work_date=work_date,
        employee_id=employee_id,
        overwrite_manual=overwrite_manual,
    )
    logger.info(
        "Olah ulang %s oleh admin %r: %s dibuat, %s diperbarui, %s manual dilewati",
        work_date, admin.username, stats["created"], stats["updated"],
        stats["skipped_manual"],
    )

    return schemas.RecomputeResponse(work_date=work_date.isoformat(), **stats)
