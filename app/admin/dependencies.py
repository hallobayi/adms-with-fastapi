"""Dependency FastAPI yang menjaga seluruh endpoint `/api/admin/*`.

Semua endpoint admin ditulis `async` tetapi `mysql-connector` blocking, jadi
setiap akses database di sini dijalankan lewat worker thread — sama seperti
handler `/iclock/*`. Bila tidak, satu query login yang lambat akan menahan
event loop dan ikut menunda device yang sedang mengunggah absensi.
"""

from __future__ import annotations

import logging
from functools import partial

import anyio.to_thread
from fastapi import Depends, HTTPException, Request, status

from app.admin import auth
from app.database import connection

logger = logging.getLogger(__name__)

#: Nama cookie sesi. `HttpOnly` wajib (JavaScript tidak boleh bisa membacanya),
#: `SameSite=Lax` mencegah CSRF pada form lintas-situs.
SESSION_COOKIE = "adms_admin_session"


async def _run_blocking(func, /, **kwargs):
    """Jalankan pekerjaan database blocking di worker thread."""
    return await anyio.to_thread.run_sync(partial(func, **kwargs))


def _credentials_error(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Cookie"},
    )


async def current_admin(request: Request) -> auth.AdminUser:
    """Ambil admin yang sedang login, atau tolak dengan 401.

    Dipasang sebagai dependency pada router admin, sehingga endpoint baru
    otomatis ikut terlindungi — tidak bisa "lupa memasang auth".
    """
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise _credentials_error("Belum login.")

    def _resolve() -> auth.AdminUser | None:
        with connection() as conn:
            admin = auth.resolve_session(conn, token)
            conn.commit()
            return admin

    admin = await _run_blocking(_resolve)
    if admin is None:
        raise _credentials_error("Sesi tidak sah atau sudah berakhir.")

    return admin


async def require_superuser(
    admin: auth.AdminUser = Depends(current_admin),
) -> auth.AdminUser:
    """Batasi endpoint ke superuser (mis. kelola akun admin lain).

    Sengaja **403, bukan 401**: admin yang sudah login tapi bukan superuser
    tidak perlu diminta login ulang — masalahnya wewenang, bukan identitas.
    """
    if not admin.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Butuh wewenang superuser.",
        )
    return admin


__all__ = ["SESSION_COOKIE", "current_admin", "require_superuser", "_run_blocking"]
