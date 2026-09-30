"""Endpoint konflik sinkronisasi `/api/admin/conflicts*`.

Konflik adalah satu-satunya tempat di mana **manusia wajib memutuskan**
(keputusan #3). Karena itu endpoint di sini tidak punya apa pun yang menyerupai
"selesaikan semua": setiap konflik dijawab satu per satu, dan setiap jawaban
meninggalkan jejak di `sync_log`.
"""

from __future__ import annotations

import logging
from functools import partial

import anyio.to_thread
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.admin import auth, queries_conflicts, schemas
from app.admin.dependencies import current_admin
from app.database import connection

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/conflicts", tags=["admin:conflicts"])


async def _run_blocking(func, /, **kwargs):
    return await anyio.to_thread.run_sync(partial(func, **kwargs))


def _conflict_out(row: dict[str, object]) -> schemas.ConflictOut:
    return schemas.ConflictOut(
        id=int(row["id"]),
        device_id=row.get("device_id"),
        serial_number=row["serial_number"],
        entity_type=row["entity_type"],
        pin=row.get("pin"),
        finger_index=row.get("finger_index"),
        action=row["action"],
        conflict_detail=row.get("conflict_detail"),
        resolved_by=row["resolved_by"],
        created_at=schemas._iso(row.get("created_at")),
    )


@router.get("", response_model=schemas.ConflictListResponse)
async def list_conflicts(
    serial_number: str | None = None,
    entity_type: str | None = None,
    resolved: bool | None = Query(
        default=False,
        description=(
            "False = antrean yang belum ditinjau (default). "
            "True = yang sudah diputuskan. Kosongkan (`?resolved=`) untuk semua."
        ),
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: auth.AdminUser = Depends(current_admin),
) -> schemas.ConflictListResponse:
    """Antrean konflik yang perlu ditinjau.

    Default `resolved=false` disengaja: pertanyaan pertama admin hampir selalu
    "apa yang harus saya kerjakan sekarang", bukan "apa yang pernah terjadi".
    """
    def _load():
        with connection() as conn:
            return queries_conflicts.list_conflicts(
                conn,
                serial_number=serial_number,
                entity_type=entity_type,
                resolved=resolved,
                limit=limit,
                offset=offset,
            )

    total, rows = await _run_blocking(_load)
    return schemas.ConflictListResponse(
        total=total, conflicts=[_conflict_out(r) for r in rows]
    )


@router.get("/summary")
async def conflict_summary(
    _: auth.AdminUser = Depends(current_admin),
) -> dict[str, int]:
    """Hitungan konflik belum/sudah ditinjau — untuk lencana di dashboard."""
    def _load():
        with connection() as conn:
            return queries_conflicts.conflict_summary(conn)

    return await _run_blocking(_load)


@router.get("/{conflict_id}", response_model=schemas.ConflictOut)
async def get_conflict(
    conflict_id: int,
    _: auth.AdminUser = Depends(current_admin),
) -> schemas.ConflictOut:
    def _load():
        with connection() as conn:
            return queries_conflicts.get_conflict(conn, conflict_id)

    row = await _run_blocking(_load)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Konflik tidak ditemukan."
        )
    if row.get("outcome") != "conflict":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Baris {conflict_id} bukan konflik (outcome={row.get('outcome')!r}).",
        )
    return _conflict_out(row)


@router.post("/{conflict_id}/resolve", response_model=schemas.ConflictResolveResponse)
async def resolve_conflict(
    conflict_id: int,
    payload: schemas.ConflictResolveRequest,
    admin: auth.AdminUser = Depends(current_admin),
) -> schemas.ConflictResolveResponse:
    """Terapkan keputusan admin atas satu konflik.

    Baris yang kalah **tidak dihapus** — hanya `is_valid` diset 0 dan
    `sync_state` menjadi `'conflict'`. Jadi bila ternyata keputusannya keliru,
    jejaknya masih bisa ditelusuri dan diperbaiki.
    """
    def _resolve():
        with connection() as conn:
            applied, message, affected = queries_conflicts.resolve_conflict(
                conn,
                conflict_id,
                resolution=payload.resolution,
                note=payload.note,
            )
            # Catat siapa yang memutuskan, terpisah dari `resolved_by` yang
            # menyimpan arah keputusan. Log server adalah tempat yang tepat:
            # tabel sync_log tidak punya kolom pelaku.
            if applied:
                logger.info(
                    "Konflik %s diputuskan %s oleh admin %r (%s baris terdampak)",
                    conflict_id, payload.resolution, admin.username, affected,
                )
                conn.commit()
            else:
                conn.rollback()
            return applied, message, affected

    applied, message, affected = await _run_blocking(_resolve)
    if not applied:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)

    return schemas.ConflictResolveResponse(
        conflict_id=conflict_id,
        resolution=payload.resolution,
        affected=affected,
        message=message,
    )
