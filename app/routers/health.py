"""Rute kesehatan aplikasi dan akar."""

from __future__ import annotations

from functools import partial

import anyio.to_thread
from fastapi import APIRouter

from app import database
from app.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/", summary="Sapaan dasar")
async def read_root() -> dict[str, str]:
    """Titik masuk sederhana untuk memastikan service hidup."""
    return {"Hello": "World"}


@router.get("/health", response_model=HealthResponse, summary="Status kesehatan")
async def health() -> HealthResponse:
    """Laporkan status aplikasi beserta keterjangkauan database.

    Selalu membalas 200 agar probe tidak menganggap aplikasi mati hanya
    karena database sedang tidak bisa dihubungi; statusnya dibedakan lewat
    field `database`.

    Ping database bersifat blocking, jadi dijalankan di worker thread: bila
    MySQL tidak menjawab, kita tidak ingin probe ini menahan event loop —
    endpoint `/iclock/*` harus tetap dilayani selama itu.
    """
    db_ok = await anyio.to_thread.run_sync(partial(database.ping))
    return HealthResponse(
        status="ok",
        database="ok" if db_ok else "degraded",
    )
