"""Rute untuk resource item."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app import store
from app.schemas import ItemListResponse, ItemResponse

router = APIRouter(prefix="/items", tags=["items"])


@router.get("", response_model=ItemListResponse)
async def list_items() -> ItemListResponse:
    """Kembalikan seluruh item yang tersedia."""
    raw = store.list_items()
    return ItemListResponse(
        total=len(raw),
        items=[ItemResponse(item_id=key, name=value) for key, value in raw.items()],
    )


@router.get("/{item_id}", response_model=ItemResponse)
async def read_item(item_id: str) -> ItemResponse:
    """Kembalikan satu item berdasarkan id."""
    name = store.get_item(item_id)
    if name is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Item {item_id!r} tidak ditemukan",
        )
    return ItemResponse(item_id=item_id, name=name)
