"""Router gabungan CRUD data master `/api/admin/*`.

Empat entitas — karyawan, shift, penugasan shift, dan hari libur — masing-masing
kini punya modul router sendiri:

======================  ============================================
`router_employees.py`   `GET|POST /employees`, `GET|PATCH|DELETE /employees/{id}`
`router_shifts.py`      `GET|POST /shifts`, `GET|PATCH|DELETE /shifts/{id}`
`router_assignments.py` `GET|POST /shift-assignments`, `DELETE .../{id}`
`router_holidays.py`    `GET|POST /holidays`, `DELETE /holidays/{id}`
======================  ============================================

Modul ini hanya merakitnya, sehingga `app/admin/__init__.py` tetap cukup
memasang satu router dan tidak perlu tahu berapa banyak sub-router di dalamnya.

Router induk sengaja **tanpa tag**: setiap sub-router punya tag sendiri, dan tag
di induk akan ikut menempel ke semua anaknya (OpenAPI menyatukannya), sehingga
`GET /employees` muncul di dua grup sekaligus.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.admin import (
    router_assignments,
    router_employees,
    router_holidays,
    router_shifts,
)

router = APIRouter()

router.include_router(router_employees.router)
router.include_router(router_shifts.router)
router.include_router(router_assignments.router)
router.include_router(router_holidays.router)

__all__ = ["router"]
