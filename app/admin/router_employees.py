"""Endpoint CRUD karyawan `/api/admin/employees*`.

Yang mengikat modul ini: **PIN karyawan adalah jembatan ke device**.
`attendance_log.pin` dicocokkan ke `employee.pin`, jadi mengubah PIN bukan
sekadar mengedit satu kolom — itu memutus tautan punch lama. Endpoint di sini
melaporkan berapa yang terputus alih-alih membiarkannya senyap.
"""

from __future__ import annotations

import logging

import mysql.connector
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.admin import auth, queries_master, schemas
from app.admin.dependencies import current_admin
from app.admin.helpers import duplicate_error
from app.database import execute, fetch

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/employees", tags=["admin:employees"])


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


@router.get("", response_model=schemas.EmployeeListResponse)
async def list_employees(
    search: str | None = None,
    department: str | None = None,
    is_active: bool | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: auth.AdminUser = Depends(current_admin),
) -> schemas.EmployeeListResponse:
    total, rows = await fetch(
        queries_master.list_employees,
        search=search,
        department=department,
        is_active=is_active,
        limit=limit,
        offset=offset,
    )
    return schemas.EmployeeListResponse(
        total=total, employees=[_employee_out(r) for r in rows]
    )


@router.get("/departments")
async def departments(_: auth.AdminUser = Depends(current_admin)) -> dict[str, list[str]]:
    """Daftar departemen unik, untuk mengisi filter di klien."""
    return {"departments": await fetch(queries_master.distinct_departments)}


@router.get("/{employee_id}", response_model=schemas.EmployeeOut)
async def get_employee(
    employee_id: int, _: auth.AdminUser = Depends(current_admin)
) -> schemas.EmployeeOut:
    row = await fetch(queries_master.get_employee, employee_id=employee_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Karyawan tidak ditemukan."
        )
    return _employee_out(row)


@router.post(
    "", response_model=schemas.EmployeeOut, status_code=status.HTTP_201_CREATED
)
async def create_employee(
    payload: schemas.EmployeeCreateRequest,
    admin: auth.AdminUser = Depends(current_admin),
) -> schemas.EmployeeOut:
    fields = payload.model_dump()

    def _create(conn) -> int:
        try:
            return queries_master.create_employee(conn, **fields)
        except mysql.connector.Error as exc:
            mapped = duplicate_error(
                exc, f"PIN {payload.pin!r} sudah dipakai karyawan lain."
            )
            if mapped:
                raise mapped from exc
            raise

    employee_id = await execute(_create)
    logger.info("Karyawan %s (PIN %s) dibuat oleh admin %r", employee_id, payload.pin, admin.username)

    row = await fetch(queries_master.get_employee, employee_id=employee_id)
    return _employee_out(row)


@router.patch("/{employee_id}", response_model=dict)
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

    def _update(conn) -> dict[str, int]:
        try:
            return queries_master.update_employee(conn, employee_id, **fields)
        except mysql.connector.Error as exc:
            mapped = duplicate_error(
                exc, f"PIN {fields.get('pin')!r} sudah dipakai karyawan lain."
            )
            if mapped:
                raise mapped from exc
            raise

    result = await execute(_update)
    if result["updated"] == 0:
        if await fetch(queries_master.get_employee, employee_id=employee_id) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Karyawan tidak ditemukan."
            )

    if result["unlinked"] or result["relinked"]:
        logger.info(
            "PIN karyawan %s diubah oleh admin %r: %s punch diputus, %s ditautkan ulang",
            employee_id, admin.username, result["unlinked"], result["relinked"],
        )

    row = await fetch(queries_master.get_employee, employee_id=employee_id)
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


@router.delete("/{employee_id}", response_model=schemas.MessageResponse)
async def delete_employee(
    employee_id: int, admin: auth.AdminUser = Depends(current_admin)
) -> schemas.MessageResponse:
    """Hapus karyawan. Punch-nya tetap ada dengan `employee_id = NULL`."""
    ok = await execute(queries_master.delete_employee, employee_id=employee_id)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Karyawan tidak ditemukan."
        )

    logger.info("Karyawan %s dihapus oleh admin %r", employee_id, admin.username)
    return schemas.MessageResponse(message="Karyawan dihapus.", id=employee_id)
