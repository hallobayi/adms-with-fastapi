"""Penyimpanan akun admin & sesi login.

Seluruh kueri untuk `admin_user` dan `admin_session` ada di sini, supaya aturan
keamanannya terlihat di satu tempat:

- **Password hanya dibandingkan lewat `security.verify_password`.** Tidak ada
  jalur lain yang boleh membaca `password_hash`.
- **Token sesi dicari berdasarkan hash-nya**, bukan token mentah, dan baris
  yang sudah `revoked_at` atau kedaluwarsa tidak pernah dikembalikan.
- **Login gagal tidak membedakan "username tidak ada" dari "password salah".**
  Membedakannya berarti memberi tahu penyerang akun mana yang benar-benar ada.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from mysql.connector import MySQLConnection

from app.admin import security

logger = logging.getLogger(__name__)

#: Umur sesi. Cukup panjang untuk shift kerja, pendek untuk membatasi jendela
#: penyalahgunaan bila sebuah token bocor.
SESSION_TTL_HOURS = 12


@dataclass(frozen=True)
class AdminUser:
    """Akun admin yang sedang login."""

    id: int
    username: str
    display_name: str | None
    is_superuser: bool


def find_user_by_username(
    conn: MySQLConnection, username: str
) -> tuple[int, str, str, bool, str] | None:
    """Ambil `(id, username, display_name, is_superuser, password_hash)`.

    Dipakai **hanya** oleh alur login, karena mengembalikan hash password.
    Mengembalikan `None` bila akun tidak ada atau tidak aktif.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, username, display_name, is_superuser, password_hash
            FROM admin_user
            WHERE username = %s AND is_active = 1
            """,
            (username,),
        )
        row = cur.fetchone()

    if row is None:
        return None
    return int(row[0]), row[1], row[2], bool(row[3]), row[4]


def touch_last_login(conn: MySQLConnection, admin_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE admin_user SET last_login_at = NOW() WHERE id = %s", (admin_id,)
        )


def update_password_hash(conn: MySQLConnection, admin_id: int, encoded: str) -> None:
    """Ganti hash password (dipakai saat rehash otomatis setelah login)."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE admin_user SET password_hash = %s WHERE id = %s",
            (encoded, admin_id),
        )


# --- Sesi -----------------------------------------------------------------


def create_session(
    conn: MySQLConnection,
    *,
    admin_id: int,
    user_agent: str | None = None,
    source_ip: str | None = None,
) -> tuple[str, datetime]:
    """Buat sesi baru. Mengembalikan `(token_mentah, kedaluwarsa)`.

    **Token mentah hanya ada di sini.** Setelah fungsi ini kembali, yang
    tersimpan di database hanya hash-nya, dan token itu tidak bisa dibaca lagi
    dari mana pun. Pemanggil bertanggung jawab mengirimkannya ke browser lewat
    cookie HttpOnly.
    """
    token = security.new_session_token()
    expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(
        hours=SESSION_TTL_HOURS
    )

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO admin_session
                (admin_user_id, token_hash, user_agent, source_ip, expires_at)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                admin_id,
                security.hash_session_token(token),
                (user_agent or "")[:255] or None,
                source_ip,
                expires_at,
            ),
        )

    return token, expires_at


def resolve_session(
    conn: MySQLConnection, token: str
) -> AdminUser | None:
    """Cari akun dari token sesi. `None` bila tidak sah/kedaluwarsa/dicabut.

    Akun yang sudah dinonaktifkan (`is_active = 0`) juga langsung ditolak —
    tanpa syarat ini, menonaktifkan akun tidak memutus sesi yang sedang jalan.
    """
    if not token:
        return None

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT u.id, u.username, u.display_name, u.is_superuser, s.id
            FROM admin_session s
            JOIN admin_user u ON u.id = s.admin_user_id
            WHERE s.token_hash = %s
              AND s.revoked_at IS NULL
              AND s.expires_at > NOW()
              AND u.is_active = 1
            """,
            (security.hash_session_token(token),),
        )
        row = cur.fetchone()

    if row is None:
        return None

    # `last_used_at` diperbarui terpisah dan kegagalannya tidak boleh
    # menggagalkan request: ini hanya telemetri, bukan syarat keamanan.
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE admin_session SET last_used_at = NOW() WHERE id = %s",
                (row[4],),
            )
    except Exception:  # noqa: BLE001
        logger.debug("Gagal memperbarui last_used_at sesi", exc_info=True)

    return AdminUser(
        id=int(row[0]),
        username=row[1],
        display_name=row[2],
        is_superuser=bool(row[3]),
    )


def revoke_session(conn: MySQLConnection, token: str) -> bool:
    """Cabut satu sesi (logout). Mengembalikan apakah ada yang dicabut."""
    if not token:
        return False
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE admin_session
            SET revoked_at = NOW()
            WHERE token_hash = %s AND revoked_at IS NULL
            """,
            (security.hash_session_token(token),),
        )
        return cur.rowcount > 0


def revoke_all_sessions(conn: MySQLConnection, admin_id: int) -> int:
    """Cabut seluruh sesi satu akun (mis. setelah ganti password)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE admin_session
            SET revoked_at = NOW()
            WHERE admin_user_id = %s AND revoked_at IS NULL
            """,
            (admin_id,),
        )
        return int(cur.rowcount)


def purge_expired_sessions(conn: MySQLConnection) -> int:
    """Hapus sesi yang sudah kedaluwarsa. Untuk dipanggil job berkala."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM admin_session WHERE expires_at < NOW()")
        return int(cur.rowcount)


# --- Manajemen akun (untuk superuser) -------------------------------------


def list_admins(conn: MySQLConnection) -> list[dict[str, object]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, username, display_name, is_active, is_superuser,
                   last_login_at, created_at
            FROM admin_user
            ORDER BY username
            """
        )
        rows = cur.fetchall()

    return [
        {
            "id": int(r[0]),
            "username": r[1],
            "display_name": r[2],
            "is_active": bool(r[3]),
            "is_superuser": bool(r[4]),
            "last_login_at": r[5],
            "created_at": r[6],
        }
        for r in rows
    ]


def create_admin(
    conn: MySQLConnection,
    *,
    username: str,
    password: str,
    display_name: str | None = None,
    is_superuser: bool = False,
) -> int:
    """Buat akun admin. Melempar `ValueError` bila username sudah dipakai."""
    encoded = security.hash_password(password)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO admin_user
                (username, display_name, password_hash, is_superuser)
            VALUES (%s, %s, %s, %s)
            """,
            (username, display_name, encoded, 1 if is_superuser else 0),
        )
        return int(cur.lastrowid)


def update_admin(
    conn: MySQLConnection,
    admin_id: int,
    *,
    display_name: str | None = None,
    is_active: bool | None = None,
    is_superuser: bool | None = None,
    password: str | None = None,
) -> bool:
    """Perbarui akun. Field yang `None` tidak diubah.

    Bila password diganti, seluruh sesi akun itu dicabut: membiarkan sesi lama
    tetap hidup membuat "ganti password" tidak benar-benar mengusir pemakai
    token yang sudah bocor.
    """
    fields: list[str] = []
    params: list[object] = []

    if display_name is not None:
        fields.append("display_name = %s")
        params.append(display_name)
    if is_active is not None:
        fields.append("is_active = %s")
        params.append(1 if is_active else 0)
    if is_superuser is not None:
        fields.append("is_superuser = %s")
        params.append(1 if is_superuser else 0)
    if password is not None:
        fields.append("password_hash = %s")
        params.append(security.hash_password(password))

    if not fields:
        return False

    params.append(admin_id)
    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE admin_user SET {', '.join(fields)} WHERE id = %s", tuple(params)
        )
        changed = cur.rowcount > 0

    if password is not None:
        revoke_all_sessions(conn, admin_id)

    return changed
