"""Endpoint CRUD data master `/api/admin/*`.

Empat entitas: karyawan, shift, penugasan shift, dan hari libur. Yang mengikat
mereka: **PIN karyawan adalah jembatan ke device**. `attendance_log.pin` dicocokkan
ke `employee.pin`, jadi mengubah PIN bukan sekadar mengedit satu kolom — itu
memutus tautan punch lama. Endpoint di sini melaporkan berapa yang terputus
alih-alih membiarkannya senyap.

Semua endpoint tulis di modul ini butuh login (`current_admin`). Penghapusan
data master tidak di-restrict ke superuser: itu pekerjaan harian admin
operasional, bukan perubahan wewenang.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from functools import partial

import anyio.to_thread
import mysql.connector
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.admin import auth, queries_master, schemas
from app.admin.dependencies import current_admin
from app.admin.queries_master import _WORK_DAY_ORDER
from app.database import connection

logger = logging.getLogger(__name__)

#: Router pengumpul. Sengaja **tanpa tag**: setiap sub-router punya tag sendiri,
#: dan tag di induk akan ikut menempel ke semua anaknya (OpenAPI menyatukannya),
#: sehingga `GET /employees` muncul di dua grup sekaligus.
router = APIRouter()


async def _run_blocking(func, /, **kwargs):
    return await anyio.to_thread.run_sync(partial(func, **kwargs))


def _duplicate_error(exc: mysql.connector.Error, message: str) -> HTTPException | None:
    """Terjemahkan galat UNIQUE MySQL (1062) menjadi 409 yang bisa dibaca."""
    if exc.errno == 1062:
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message)
    return None


def _time_str(value: object) -> str:
    """Normalisasi `TIME` MySQL (datetime.timedelta) menjadi 'HH:MM:SS'."""
    if isinstance(value, timedelta):
        total = int(value.total_seconds())
        return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"
    return str(value)


# --- Karyawan -------------------------------------------------------------

employees_router = APIRouter(prefix="/employees", tags=["admin:employees"])


def _employee_out(row: dict[str, object]) -> schemas.EmployeeOut:
    return schemas.EmployeeOut(
        id=int(row["id"]),
        pin=row["pin"],
        name=row["name"],
        employee_code=row.get("employee_code"),
        department=row.get("department"),
        position=row.get("position"),
        email=row.get("email"),
        phone=row.get("phone"),
        joined_at=schemas._iso(row.get("joined_at")),
        resigned_at=schemas._iso(row.get("resigned_at")),
        is_active=bool(row.get("is_active")),
    )


@employees_router.get("", response_model=schemas.EmployeeListResponse)
async def list_employees(
    search: str | None = None,
    department: str | None = None,
    is_active: bool | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: auth.AdminUser = Depends(current_admin),
) -> schemas.EmployeeListResponse:
    def _load():
        with connection() as conn:
            return queries_master.list_employees(
                conn,
                search=search,
                department=department,
                is_active=is_active,
                limit=limit,
                offset=offset,
            )

    total, rows = await _run_blocking(_load)
    return schemas.EmployeeListResponse(
        total=total, employees=[_employee_out(r) for r in rows]
    )


@employees_router.get("/departments")
async def departments(_: auth.AdminUser = Depends(current_admin)) -> dict[str, list[str]]:
    """Daftar departemen unik, untuk mengisi filter di klien."""
    def _load():
        with connection() as conn:
            return queries_master.distinct_departments(conn)

    return {"departments": await _run_blocking(_load)}


@employees_router.get("/{employee_id}", response_model=schemas.EmployeeOut)
async def get_employee(
    employee_id: int, _: auth.AdminUser = Depends(current_admin)
) -> schemas.EmployeeOut:
    def _load():
        with connection() as conn:
            return queries_master.get_employee(conn, employee_id)

    row = await _run_blocking(_load)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Karyawan tidak ditemukan."
        )
    return _employee_out(row)


@employees_router.post(
    "", response_model=schemas.EmployeeOut, status_code=status.HTTP_201_CREATED
)
async def create_employee(
    payload: schemas.EmployeeCreateRequest,
    admin: auth.AdminUser = Depends(current_admin),
) -> schemas.EmployeeOut:
    fields = payload.model_dump()

    def _create():
        with connection() as conn:
            try:
                employee_id = queries_master.create_employee(conn, **fields)
            except mysql.connector.Error as exc:
                conn.rollback()
                mapped = _duplicate_error(
                    exc, f"PIN {payload.pin!r} sudah dipakai karyawan lain."
                )
                if mapped:
                    raise mapped from exc
                raise
            conn.commit()
            return employee_id

    employee_id = await _run_blocking(_create)
    logger.info("Karyawan %s (PIN %s) dibuat oleh admin %r", employee_id, payload.pin, admin.username)

    def _reload():
        with connection() as conn:
            return queries_master.get_employee(conn, employee_id)

    return _employee_out(await _run_blocking(_reload))


@employees_router.patch("/{employee_id}", response_model=dict)
async def update_employee(
    employee_id: int,
    payload: schemas.EmployeeUpdateRequest,
    admin: auth.AdminUser = Depends(current_admin),
) -> dict:
    """Perbarui karyawan. Bila PIN berubah, tautan punch lama ikut dilaporkan.

    Punch lama **tidak** ditulis ulang secara diam-diam: punch adalah rekaman
    mentah dari device, dan mengubahnya berarti memalsukan jejak. Yang dilakukan
    adalah memutus tautan yang tidak lagi cocok dan melaporkan jumlahnya.
    """
    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Tidak ada field yang diubah."
        )

    def _update():
        with connection() as conn:
            try:
                result = queries_master.update_employee(conn, employee_id, **fields)
            except mysql.connector.Error as exc:
                conn.rollback()
                mapped = _duplicate_error(
                    exc, f"PIN {fields.get('pin')!r} sudah dipakai karyawan lain."
                )
                if mapped:
                    raise mapped from exc
                raise
            conn.commit()
            return result

    result = await _run_blocking(_update)
    if result["updated"] == 0:
        def _exists() -> bool:
            with connection() as conn:
                return queries_master.get_employee(conn, employee_id) is not None

        if not await _run_blocking(_exists):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Karyawan tidak ditemukan."
            )

    if result["unlinked"] or result["relinked"]:
        logger.info(
            "PIN karyawan %s diubah oleh admin %r: %s punch diputus, %s ditautkan ulang",
            employee_id, admin.username, result["unlinked"], result["relinked"],
        )

    def _reload():
        with connection() as conn:
            return queries_master.get_employee(conn, employee_id)

    row = await _run_blocking(_reload)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Karyawan tidak ditemukan."
        )

    return {
        "employee": _employee_out(row).model_dump(),
        "unlinked_punches": result["unlinked"],
        "relinked_punches": result["relinked"],
        "message": (
            f"PIN berubah: {result['unlinked']} punch tidak lagi tertaut, "
            f"{result['relinked']} ditautkan ulang."
            if result["unlinked"] or result["relinked"]
            else "Perubahan disimpan."
        ),
    }


@employees_router.delete("/{employee_id}", response_model=schemas.MessageResponse)
async def delete_employee(
    employee_id: int, admin: auth.AdminUser = Depends(current_admin)
) -> schemas.MessageResponse:
    """Hapus karyawan. Punch-nya tetap ada dengan `employee_id = NULL`."""
    def _delete() -> bool:
        with connection() as conn:
            ok = queries_master.delete_employee(conn, employee_id)
            conn.commit()
            return ok

    if not await _run_blocking(_delete):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Karyawan tidak ditemukan."
        )

    logger.info("Karyawan %s dihapus oleh admin %r", employee_id, admin.username)
    return schemas.MessageResponse(message="Karyawan dihapus.", id=employee_id)


router.include_router(employees_router)


# --- Shift ----------------------------------------------------------------

shifts_router = APIRouter(prefix="/shifts", tags=["admin:shifts"])


def _shift_out(row: dict[str, object]) -> schemas.ShiftOut:
    return schemas.ShiftOut(
        id=int(row["id"]),
        name=row["name"],
        start_time=_time_str(row["start_time"]),
        end_time=_time_str(row["end_time"]),
        late_tolerance_min=int(row.get("late_tolerance_min") or 0),
        early_leave_tol_min=int(row.get("early_leave_tol_min") or 0),
        is_overnight=bool(row.get("is_overnight")),
        is_active=bool(row.get("is_active")),
    )


@shifts_router.get("", response_model=schemas.ShiftListResponse)
async def list_shifts(
    is_active: bool | None = None,
    _: auth.AdminUser = Depends(current_admin),
) -> schemas.ShiftListResponse:
    def _load():
        with connection() as conn:
            return queries_master.list_shifts(conn, is_active=is_active)

    rows = await _run_blocking(_load)
    return schemas.ShiftListResponse(total=len(rows), shifts=[_shift_out(r) for r in rows])


@shifts_router.get("/{shift_id}", response_model=schemas.ShiftOut)
async def get_shift(
    shift_id: int, _: auth.AdminUser = Depends(current_admin)
) -> schemas.ShiftOut:
    def _load():
        with connection() as conn:
            return queries_master.get_shift(conn, shift_id)

    row = await _run_blocking(_load)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Shift tidak ditemukan."
        )
    return _shift_out(row)


@shifts_router.post("", response_model=schemas.ShiftOut, status_code=status.HTTP_201_CREATED)
async def create_shift(
    payload: schemas.ShiftCreateRequest,
    admin: auth.AdminUser = Depends(current_admin),
) -> schemas.ShiftOut:
    fields = payload.model_dump()

    def _create() -> int:
        with connection() as conn:
            try:
                shift_id = queries_master.create_shift(conn, **fields)
            except mysql.connector.Error as exc:
                conn.rollback()
                mapped = _duplicate_error(exc, f"Nama shift {payload.name!r} sudah dipakai.")
                if mapped:
                    raise mapped from exc
                raise
            conn.commit()
            return shift_id

    shift_id = await _run_blocking(_create)
    logger.info("Shift %s (%s) dibuat oleh admin %r", shift_id, payload.name, admin.username)

    def _reload():
        with connection() as conn:
            return queries_master.get_shift(conn, shift_id)

    return _shift_out(await _run_blocking(_reload))


@shifts_router.patch("/{shift_id}", response_model=schemas.ShiftOut)
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

    def _update() -> bool:
        with connection() as conn:
            try:
                changed = queries_master.update_shift(conn, shift_id, **fields)
            except mysql.connector.Error as exc:
                conn.rollback()
                mapped = _duplicate_error(exc, "Nama shift sudah dipakai.")
                if mapped:
                    raise mapped from exc
                raise
            conn.commit()
            return changed

    changed = await _run_blocking(_update)
    if not changed:
        def _exists() -> bool:
            with connection() as conn:
                return queries_master.get_shift(conn, shift_id) is not None

        if not await _run_blocking(_exists):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Shift tidak ditemukan."
            )

    logger.info("Shift %s diperbarui oleh admin %r: %s", shift_id, admin.username, sorted(fields))

    def _reload():
        with connection() as conn:
            return queries_master.get_shift(conn, shift_id)

    row = await _run_blocking(_reload)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Shift tidak ditemukan."
        )
    return _shift_out(row)


@shifts_router.delete("/{shift_id}", response_model=schemas.MessageResponse)
async def delete_shift(
    shift_id: int, admin: auth.AdminUser = Depends(current_admin)
) -> schemas.MessageResponse:
    """Hapus shift. Ditolak 409 bila masih dipakai penugasan."""
    def _delete() -> tuple[bool, str]:
        with connection() as conn:
            ok, message = queries_master.delete_shift(conn, shift_id)
            if ok:
                conn.commit()
            else:
                conn.rollback()
            return ok, message

    ok, message = await _run_blocking(_delete)
    if not ok:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message)

    logger.info("Shift %s dihapus oleh admin %r", shift_id, admin.username)
    return schemas.MessageResponse(message=message, id=shift_id)


router.include_router(shifts_router)


# --- Penugasan shift ------------------------------------------------------


def _work_days_list(value: object) -> list[str]:
    """Ubah kolom `SET` MySQL menjadi daftar hari yang terurut.

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
    return [day for day in _WORK_DAY_ORDER if day in raw]


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
        work_days=_work_days_list(row.get("work_days")),
    )


assignments_router = APIRouter(prefix="/shift-assignments", tags=["admin:shifts"])


@assignments_router.get("", response_model=schemas.ShiftAssignmentListResponse)
async def list_assignments(
    employee_id: int | None = None,
    shift_id: int | None = None,
    active_on: date | None = None,
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: auth.AdminUser = Depends(current_admin),
) -> schemas.ShiftAssignmentListResponse:
    def _load():
        with connection() as conn:
            return queries_master.list_shift_assignments(
                conn,
                employee_id=employee_id,
                shift_id=shift_id,
                active_on=active_on,
                limit=limit,
                offset=offset,
            )

    total, rows = await _run_blocking(_load)
    return schemas.ShiftAssignmentListResponse(
        total=total, assignments=[_assignment_out(r) for r in rows]
    )


@assignments_router.post(
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

    def _create() -> int:
        with connection() as conn:
            try:
                assignment_id = queries_master.create_shift_assignment(conn, **fields)
            except mysql.connector.Error as exc:
                conn.rollback()
                if exc.errno in (1062, 1452):
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=(
                            "Karyawan atau shift tidak ada, atau sudah punya penugasan "
                            "dengan tanggal mulai yang sama."
                        ),
                    ) from exc
                raise
            conn.commit()
            return assignment_id

    assignment_id = await _run_blocking(_create)
    logger.info(
        "Penugasan shift %s dibuat oleh admin %r (karyawan=%s shift=%s)",
        assignment_id, admin.username, payload.employee_id, payload.shift_id,
    )
    return schemas.MessageResponse(message="Penugasan dibuat.", id=assignment_id)


@assignments_router.delete("/{assignment_id}", response_model=schemas.MessageResponse)
async def delete_assignment(
    assignment_id: int, admin: auth.AdminUser = Depends(current_admin)
) -> schemas.MessageResponse:
    def _delete() -> bool:
        with connection() as conn:
            ok = queries_master.delete_shift_assignment(conn, assignment_id)
            conn.commit()
            return ok

    if not await _run_blocking(_delete):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Penugasan tidak ditemukan."
        )

    logger.info("Penugasan %s dihapus oleh admin %r", assignment_id, admin.username)
    return schemas.MessageResponse(message="Penugasan dihapus.", id=assignment_id)


router.include_router(assignments_router)


# --- Hari libur -----------------------------------------------------------

holidays_router = APIRouter(prefix="/holidays", tags=["admin:holidays"])


def _holiday_out(row: dict[str, object]) -> schemas.HolidayOut:
    hd = row["holiday_date"]
    return schemas.HolidayOut(
        id=int(row["id"]),
        holiday_date=hd.isoformat() if isinstance(hd, date) else str(hd),
        name=row["name"],
        is_recurring=bool(row.get("is_recurring")),
    )


@holidays_router.get("", response_model=schemas.HolidayListResponse)
async def list_holidays(
    year: int | None = None,
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: auth.AdminUser = Depends(current_admin),
) -> schemas.HolidayListResponse:
    def _load():
        with connection() as conn:
            return queries_master.list_holidays(
                conn, year=year, limit=limit, offset=offset
            )

    total, rows = await _run_blocking(_load)
    return schemas.HolidayListResponse(
        total=total, holidays=[_holiday_out(r) for r in rows]
    )


@holidays_router.post(
    "", response_model=schemas.HolidayOut, status_code=status.HTTP_201_CREATED
)
async def create_holiday(
    payload: schemas.HolidayCreateRequest,
    admin: auth.AdminUser = Depends(current_admin),
) -> schemas.HolidayOut:
    """Tambah hari libur.

    `is_recurring = 1` berarti tanggalnya diulang setiap tahun (mis. 17 Agustus,
    bukan hari raya yang bergeser seperti Idul Fitri — untuk yang bergeser,
    tambahkan per tahun).
    """
    fields = payload.model_dump()

    def _create() -> int:
        with connection() as conn:
            try:
                holiday_id = queries_master.create_holiday(conn, **fields)
            except mysql.connector.Error as exc:
                conn.rollback()
                mapped = _duplicate_error(
                    exc, f"Hari libur pada {payload.holiday_date} sudah ada."
                )
                if mapped:
                    raise mapped from exc
                raise
            conn.commit()
            return holiday_id

    holiday_id = await _run_blocking(_create)
    logger.info(
        "Hari libur %s (%s) ditambahkan oleh admin %r",
        holiday_id, payload.holiday_date, admin.username,
    )

    def _reload():
        with connection() as conn:
            _, rows = queries_master.list_holidays(conn, limit=500)
            return next((r for r in rows if int(r["id"]) == holiday_id), None)

    row = await _run_blocking(_reload)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Hari libur dibuat tetapi gagal dibaca kembali.",
        )
    return _holiday_out(row)


@holidays_router.delete("/{holiday_id}", response_model=schemas.MessageResponse)
async def delete_holiday(
    holiday_id: int, admin: auth.AdminUser = Depends(current_admin)
) -> schemas.MessageResponse:
    def _delete() -> bool:
        with connection() as conn:
            ok = queries_master.delete_holiday(conn, holiday_id)
            conn.commit()
            return ok

    if not await _run_blocking(_delete):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Hari libur tidak ditemukan."
        )

    logger.info("Hari libur %s dihapus oleh admin %r", holiday_id, admin.username)
    return schemas.MessageResponse(message="Hari libur dihapus.", id=holiday_id)


router.include_router(holidays_router)
