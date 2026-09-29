"""Titik masuk aplikasi ADMS.

Jalankan dengan:
    uvicorn main:app --reload
"""

from __future__ import annotations

from app.application import create_app

app = create_app()

__all__ = ["app"]
