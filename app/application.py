"""Perakitan aplikasi FastAPI (application factory).

Pembuatan instance `FastAPI` ditaruh di sebuah fungsi pabrik supaya mudah
menguji aplikasi dengan konfigurasi berbeda tanpa efek samping saat impor.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.admin import router as admin_router
from app.config import Settings, get_settings
from app.iclock import router as iclock_router
from app.logger import configure_logging
from app.routers import health, items

logger = logging.getLogger(__name__)

#: Prefiks tempat SPA admin disajikan. Sengaja berbeda dari API (`/api/admin`)
#: supaya rute sisi klien (`/admin/devices/3`) tidak pernah bertabrakan dengan
#: endpoint JSON.
UI_PREFIX = "/admin"


def _mount_admin_ui(app: FastAPI, settings: Settings) -> None:
    """Sajikan SPA admin yang sudah dibangun, bila ada.

    Kegagalan di sini **tidak** boleh menggagalkan start server: API adalah
    bagian yang wajib hidup (device bergantung padanya), sedangkan UI hanya
    cara manusia melihatnya. Karena itu dist yang belum dibangun hanya
    menghasilkan peringatan, bukan exception.
    """
    dist = Path(settings.frontend_dist)
    index = dist / "index.html"
    if not index.is_file():
        logger.warning(
            "SERVE_UI aktif tetapi %s tidak ada — UI tidak dipasang. "
            "Bangun dulu: cd frontend && npm install && npm run build",
            index,
        )
        return

    assets = dist / "assets"
    if assets.is_dir():
        app.mount(
            f"{UI_PREFIX}/assets",
            StaticFiles(directory=assets),
            name="admin-assets",
        )

    root = dist.resolve()

    @app.get(UI_PREFIX, include_in_schema=False)
    @app.get(f"{UI_PREFIX}/{{path:path}}", include_in_schema=False)
    async def admin_spa(path: str = "") -> FileResponse:
        """Layani berkas statis, atau `index.html` untuk rute sisi klien.

        Tanpa fallback ini, membuka `/admin/devices/3` lalu menekan refresh akan
        menghasilkan 404: rutenya hanya ada di router sisi klien, bukan di
        server. Pemeriksaan `root in candidate.parents` menjaga agar `../`
        tidak bisa dipakai membaca berkas di luar direktori build.
        """
        if path:
            candidate = (dist / path).resolve()
            if root in candidate.parents and candidate.is_file():
                return FileResponse(candidate)
        return FileResponse(index)

    logger.info("UI admin disajikan di %s (dari %s)", UI_PREFIX, dist)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Bangun dan konfigurasikan instance FastAPI."""
    app_settings = settings or get_settings()

    # Konfigurasi log lebih dulu, sebelum apa pun berjalan: tanpa ini seluruh
    # `logger.info(...)` di jalur ingest dan dashboard tidak pernah terlihat
    # (root logger tanpa handler). Lihat `app/logger.py`.
    configure_logging(app_settings.log_level)

    app = FastAPI(
        title=f"{app_settings.app_name} API",
        description="Attendance Device Management System",
        version="0.1.0",
        debug=app_settings.debug,
        docs_url=app_settings.docs_url,
        redoc_url=app_settings.redoc_url,
    )

    app.include_router(health.router)
    app.include_router(items.router)

    # Endpoint protokol device. Dipasang tanpa syarat: tanpa ini tidak ada
    # cara apa pun bagi device untuk mengetahui keberadaan server.
    app.include_router(iclock_router.router)

    # Dashboard admin (`/api/admin/*`). Seluruh endpoint-nya terlindungi sesi —
    # penjagaannya ada di dependency `current_admin`, bukan di sini.
    app.include_router(admin_router)

    # SPA admin (`/admin`). Dipasang paling akhir supaya rute API sudah
    # terdaftar lebih dulu dan tidak mungkin tertutup oleh catch-all-nya.
    if app_settings.serve_ui:
        _mount_admin_ui(app, app_settings)

    logger.debug("Aplikasi %s siap", app_settings.app_name)
    return app
