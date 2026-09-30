"""Endpoint autentikasi `/api/admin/auth/*`.

Alur: `POST /login` menaruh token sesi di cookie HttpOnly, `GET /me` memeriksa
sesi yang sedang berjalan, `POST /logout` mencabutnya.

Dua hal yang disengaja:

- **Cookie HttpOnly + SameSite=Lax.** Token tidak pernah bisa dibaca JavaScript
  (mencegah pencurian lewat XSS) dan tidak ikut terkirim pada permintaan
  lintas-situs (mencegah CSRF pada form).
- **`secure` mengikuti DEBUG.** Di produksi (DEBUG=false) cookie wajib HTTPS;
  di pengembangan lokal, `secure` akan membuat cookie tidak terkirim lewat
  `http://localhost` dan login tampak "berhasil tapi tidak masuk".
"""

from __future__ import annotations

import logging
from functools import partial

import anyio.to_thread
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.admin import auth, schemas
from app.admin.dependencies import SESSION_COOKIE, current_admin
from app.config import get_settings
from app.database import connection

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["admin:auth"])

#: Pesan yang sama untuk "username tidak ada" dan "password salah" — membedakan
#: keduanya berarti memberi tahu penyerang akun mana yang benar-benar ada.
_INVALID_CREDENTIALS = "Username atau password salah."


async def _run_blocking(func, /, **kwargs):
    return await anyio.to_thread.run_sync(partial(func, **kwargs))


def _set_session_cookie(response: Response, token: str, expires_at) -> None:
    settings = get_settings()
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        secure=not settings.debug,
        max_age=auth.SESSION_TTL_HOURS * 3600,
        path="/",
    )


@router.post("/login", response_model=schemas.LoginResponse)
async def login(
    payload: schemas.LoginRequest, request: Request, response: Response
) -> schemas.LoginResponse:
    """Masuk dan mulai sesi.

    Verifikasi password sengaja **selalu** dijalankan biarpun username tidak
    ditemukan — ini disebut *dummy verify*. Tanpa itu, request untuk username
    yang tidak ada akan kembali jauh lebih cepat (tidak ada hashing 600k
    iterasi), dan selisih waktu itu cukup untuk menebak username mana yang
    sah.
    """
    username = payload.username.strip()

    def _attempt():
        with connection() as conn:
            row = auth.find_user_by_username(conn, username)
            if row is None:
                # Dummy verify agar waktu respons seragam.
                auth.security.verify_password(
                    payload.password,
                    "pbkdf2_sha256$600000$AAAAAAAAAAAAAAAAAAAAAA==$"
                    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
                )
                conn.commit()
                return None

            admin_id, uname, display, is_super, password_hash = row
            if not auth.security.verify_password(payload.password, password_hash):
                conn.commit()
                return None

            # Parameter hashing bisa naik seiring waktu; perbarui diam-diam
            # supaya akun lama ikut kuat tanpa memaksa ganti password.
            if auth.security.needs_rehash(password_hash):
                auth.update_password_hash(
                    conn, admin_id, auth.security.hash_password(payload.password)
                )

            auth.touch_last_login(conn, admin_id)
            token, expires_at = auth.create_session(
                conn,
                admin_id=admin_id,
                user_agent=request.headers.get("user-agent"),
                source_ip=request.client.host if request.client else None,
            )
            conn.commit()
            return (admin_id, uname, display, is_super, token, expires_at)

    result = await _run_blocking(_attempt)

    if result is None:
        logger.warning("Login gagal untuk username=%r", username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=_INVALID_CREDENTIALS
        )

    admin_id, uname, display, is_super, token, expires_at = result
    _set_session_cookie(response, token, expires_at)
    logger.info("Admin %r masuk", uname)

    return schemas.LoginResponse(
        admin=schemas.AdminMe(
            id=admin_id, username=uname, display_name=display, is_superuser=is_super
        ),
        expires_at=expires_at.isoformat(sep=" "),
    )


@router.post("/logout", response_model=schemas.MessageResponse)
async def logout(request: Request, response: Response) -> schemas.MessageResponse:
    """Cabut sesi dan hapus cookie.

    Selalu membalas sukses, termasuk bila tidak ada cookie — pemanggil tidak
    perlu tahu apakah sesinya memang ada, dan logout harus terasa idempoten.
    """
    token = request.cookies.get(SESSION_COOKIE)

    if token:
        def _revoke() -> bool:
            with connection() as conn:
                revoked = auth.revoke_session(conn, token)
                conn.commit()
                return revoked

        await _run_blocking(_revoke)

    response.delete_cookie(SESSION_COOKIE, path="/")
    return schemas.MessageResponse(message="Sesi diakhiri.")


@router.get("/me", response_model=schemas.AdminMe)
async def me(admin: auth.AdminUser = Depends(current_admin)) -> schemas.AdminMe:
    """Identitas admin yang sedang login. 401 bila belum/tidak lagi login."""
    return schemas.AdminMe(
        id=admin.id,
        username=admin.username,
        display_name=admin.display_name,
        is_superuser=admin.is_superuser,
    )


@router.post("/password", response_model=schemas.MessageResponse)
async def change_password(
    payload: schemas.PasswordChangeRequest,
    admin: auth.AdminUser = Depends(current_admin),
) -> schemas.MessageResponse:
    """Ganti password sendiri, lalu cabut sesi lain.

    Sesi lain dicabut karena alasan mengganti password biasanya justru
    "saya tidak yakin siapa lagi yang punya akses" — membiarkan sesi lama
    hidup membuat tindakan itu tidak ada gunanya. Sesi yang dipakai sekarang
    ikut tercabut, sehingga admin perlu login ulang.
    """
    def _change() -> bool:
        with connection() as conn:
            row = auth.find_user_by_username(conn, admin.username)
            if row is None:
                conn.commit()
                return False
            if not auth.security.verify_password(payload.current_password, row[4]):
                conn.commit()
                return False

            auth.update_password_hash(
                conn, admin.id, auth.security.hash_password(payload.new_password)
            )
            auth.revoke_all_sessions(conn, admin.id)
            conn.commit()
            return True

    ok = await _run_blocking(_change)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password saat ini salah.",
        )

    return schemas.MessageResponse(
        message="Password diganti. Seluruh sesi dicabut — silakan login ulang."
    )
