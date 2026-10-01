"""Endpoint kelola akun admin `/api/admin/accounts*` — khusus superuser.

Dipisah dari `router_auth.py` karena wewenangnya berbeda: `router_auth.py`
mengurus **diri sendiri** (login, logout, ganti password sendiri), sedangkan
modul ini mengurus **akun orang lain**, dan itu hanya boleh dilakukan superuser.

Penjagaan yang penting di sini: superuser tidak bisa menurunkan wewenang dirinya
sendiri lewat `PATCH`. Tanpa aturan itu, satu salah klik bisa membuat sistem
tidak punya superuser lagi — dan tidak ada jalan masuk untuk memperbaikinya
selain mengubah database manual.
"""

from __future__ import annotations

import logging
from typing import Any

import mysql.connector
from fastapi import APIRouter, Depends, HTTPException, status

from app.admin import auth, schemas
from app.admin.dependencies import require_superuser
from app.database import execute, fetch

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/accounts", tags=["admin:accounts"])


def _account_out(row: dict[str, object]) -> dict[str, object]:
    return {
        "id": int(row["id"]),
        "username": row["username"],
        "display_name": row.get("display_name"),
        "is_active": bool(row.get("is_active")),
        "is_superuser": bool(row.get("is_superuser")),
        "last_login_at": schemas._iso(row.get("last_login_at")),
        "created_at": schemas._iso(row.get("created_at")),
    }


def _create_admin(conn: Any, **fields: object) -> int:
    """Buat akun, terjemahkan galat UNIQUE (1062) menjadi 409 yang bisa dibaca.

    `execute()` yang memanggilnya akan meng-`rollback` transaksi begitu
    `HTTPException` dilempar dari sini, jadi tidak perlu rollback manual.
    """
    try:
        return auth.create_admin(conn, **fields)
    except mysql.connector.Error as exc:
        if exc.errno == 1062:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Username {fields.get('username')!r} sudah dipakai.",
            ) from exc
        raise


@router.get("")
async def list_accounts(
    _: auth.AdminUser = Depends(require_superuser),
) -> dict[str, object]:
    rows = await fetch(auth.list_admins)
    return {"total": len(rows), "accounts": [_account_out(r) for r in rows]}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_account(
    payload: schemas.AdminCreateRequest,
    admin: auth.AdminUser = Depends(require_superuser),
) -> dict[str, object]:
    admin_id = await execute(
        _create_admin,
        username=payload.username,
        password=payload.password,
        display_name=payload.display_name,
        is_superuser=payload.is_superuser,
    )
    logger.info(
        "Akun admin %r (id=%s) dibuat oleh superuser %r",
        payload.username, admin_id, admin.username,
    )
    return {
        "id": admin_id,
        "username": payload.username,
        "is_superuser": payload.is_superuser,
        "message": "Akun admin dibuat.",
    }


@router.patch("/{admin_id}")
async def update_account(
    admin_id: int,
    payload: schemas.AdminUpdateRequest,
    admin: auth.AdminUser = Depends(require_superuser),
) -> dict[str, object]:
    """Perbarui akun admin lain.

    Ganti password selalu mencabut seluruh sesi akun itu (lihat
    `auth.update_admin`), sehingga pemakai token yang sudah bocor benar-benar
    terlempar keluar.
    """
    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Tidak ada field yang diubah."
        )

    # Jangan biarkan superuser melucuti wewenangnya sendiri.
    if admin_id == admin.id:
        if fields.get("is_superuser") is False:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Tidak bisa menurunkan wewenang superuser akun sendiri.",
            )
        if fields.get("is_active") is False:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Tidak bisa menonaktifkan akun sendiri.",
            )

    changed = await execute(auth.update_admin, admin_id=admin_id, **fields)
    if not changed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Akun tidak ditemukan atau tidak ada perubahan.",
        )

    logger.info(
        "Akun admin %s diperbarui oleh superuser %r: %s",
        admin_id, admin.username, sorted(fields),
    )
    return {
        "id": admin_id,
        "message": (
            "Akun diperbarui. Sesi akun itu dicabut."
            if "password" in fields
            else "Akun diperbarui."
        ),
    }
