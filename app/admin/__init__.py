"""Dashboard admin: autentikasi, penyimpanan, dan endpoint /api/admin/*.

Berbeda dengan `app/iclock/` yang melayani device tanpa autentikasi, paket ini
melayani **manusia** lewat browser dan seluruh endpoint-nya wajib login.
Pemisahan ini disengaja: aturan keamanan kedua sisi berlawanan, dan
mencampurnya di satu modul adalah cara tercepat membuat batasnya kabur.

Modul ini menyediakan `router`, satu `APIRouter` gabungan di bawah prefiks
`/api/admin`, sehingga `app/application.py` cukup memasang satu router dan
setiap endpoint baru otomatis ikut terlindungi.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.admin import (
    router_accounts,
    router_attendance,
    router_auth,
    router_conflicts,
    router_dashboard,
    router_devices,
    router_master,
)

#: Prefiks tunggal seluruh API dashboard.
API_PREFIX = "/api/admin"

router = APIRouter(prefix=API_PREFIX)

router.include_router(router_auth.router)
router.include_router(router_dashboard.router)
router.include_router(router_devices.router)
router.include_router(router_devices.requests_router)
router.include_router(router_conflicts.router)
router.include_router(router_attendance.router)
router.include_router(router_master.router)
router.include_router(router_accounts.router)

__all__ = ["router", "API_PREFIX"]
