"""Endpoint ringkasan `/api/admin/dashboard`.

Satu panggilan untuk mengisi kepala dashboard: kondisi device, konflik yang
menunggu ditinjau, dan angka kehadiran hari ini.

Sengaja digabung dalam satu endpoint, bukan tiga: ini dipanggil setiap kali
dashboard dibuka, dan tiga request terpisah berarti tiga kali perjalanan ke
database untuk data yang selalu ditampilkan bersama-sama.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query

from app.admin import auth, queries_attendance, queries_conflicts, queries_devices
from app.admin.dependencies import current_admin
from app.database import fetch

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["admin:dashboard"])


def _load_summary(conn, *, days: int) -> dict[str, int]:
    """Gabungkan ketiga ringkasan dalam **satu** koneksi.

    Ketiganya berbagi satu koneksi dengan sengaja: tiga ringkasan ini selalu
    ditampilkan bersama, dan membuka tiga koneksi terpisah hanya menambah
    perjalanan ke database tanpa menambah informasi.
    """
    summary: dict[str, int] = {}
    summary.update(queries_devices.device_health_summary(conn))
    summary.update(queries_conflicts.conflict_summary(conn))
    summary.update(queries_attendance.attendance_summary(conn, days=days))
    return summary


@router.get("")
async def dashboard(
    days: int = Query(
        default=1, ge=1, le=90, description="Jendela ringkasan kehadiran, dalam hari."
    ),
    _: auth.AdminUser = Depends(current_admin),
) -> dict[str, int]:
    """Ringkasan gabungan: device + konflik + kehadiran.

    Dipakai sebagai lencana angka di dashboard; bila ada satu bagian yang gagal
    dihitung, lebih baik seluruh endpoint gagal daripada menampilkan dashboard
    yang angkanya diam-diam nol.
    """
    return await fetch(_load_summary, days=days)
