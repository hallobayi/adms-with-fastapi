"""Skema request/response API.

Model Pydantic di sini membuat bentuk respons terdokumentasi otomatis di
OpenAPI dan mencegah perubahan bentuk respons yang tidak disengaja.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Status kesehatan aplikasi."""

    status: str = Field(examples=["ok"])
    database: str = Field(
        description="ok bila MySQL terjangkau, degraded bila tidak.",
        examples=["ok"],
    )


class ItemResponse(BaseModel):
    """Satu item beserta id-nya."""

    item_id: str = Field(examples=["foo"])
    name: str = Field(examples=["The Foo Wrestless"])


class ItemListResponse(BaseModel):
    """Daftar seluruh item."""

    total: int
    items: list[ItemResponse]
