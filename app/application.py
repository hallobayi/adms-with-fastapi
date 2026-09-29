"""Perakitan aplikasi FastAPI (application factory).

Pembuatan instance `FastAPI` ditaruh di sebuah fungsi pabrik supaya mudah
menguji aplikasi dengan konfigurasi berbeda tanpa efek samping saat impor.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI

from app.config import Settings, get_settings
from app.routers import health, items

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Bangun dan konfigurasikan instance FastAPI."""
    app_settings = settings or get_settings()

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

    logger.debug("Aplikasi %s siap", app_settings.app_name)
    return app
