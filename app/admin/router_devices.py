"""Endpoint monitoring device `/api/admin/devices*`.

Ini menjawab pertanyaan operasional yang paling sering muncul: **"device ini
kenapa diam?"** Karena itu ada tiga lapis jawaban — status device, arsip
request mentah, dan ringkasan kesehatan 24 jam terakhir.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.admin import auth, queries_devices, schemas
from app.admin.dependencies import current_admin
from app.database import execute, fetch
from app.iclock import timezones

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/devices", tags=["admin:devices"])


def _device_out(row: dict[str, object]) -> schemas.DeviceOut:
    return schemas.DeviceOut(
        id=int(row["id"]),
        serial_number=row["serial_number"],
        display_name=row.get("display_name"),
        location=row.get("location"),
        status=row["status"],
        model=row.get("model"),
        firmware=row.get("firmware"),
        ip_address=row.get("ip_address"),
        tz_name=row.get("tz_name"),
        last_seen_at=schemas._iso(row.get("last_seen_at")),
        last_handshake_at=schemas._iso(row.get("last_handshake_at")),
        last_attlog_at=schemas._iso(row.get("last_attlog_at")),
        created_at=schemas._iso(row.get("created_at")),
        attlog_count=int(row.get("attlog_count") or 0),
        pending_commands=int(row.get("pending_commands") or 0),
        unlinked_punches=int(row.get("unlinked_punches") or 0),
    )


def _request_out(row: dict[str, object], *, body_raw: str | None = None) -> schemas.RequestOut:
    """Bentuk satu baris arsip request. `body_raw` hanya diisi pada endpoint detail."""
    return schemas.RequestOut(
        id=int(row["id"]),
        device_id=row.get("device_id"),
        serial_number=row["serial_number"],
        endpoint=row["endpoint"],
        http_method=row["http_method"],
        table_name=row.get("table_name"),
        body_bytes=int(row.get("body_bytes") or 0),
        line_count=int(row.get("line_count") or 0),
        parsed_count=int(row.get("parsed_count") or 0),
        stored_count=int(row.get("stored_count") or 0),
        dup_count=int(row.get("dup_count") or 0),
        failed_count=int(row.get("failed_count") or 0),
        process_status=row["process_status"],
        error_message=row.get("error_message"),
        source_ip=row.get("source_ip"),
        created_at=schemas._iso(row.get("created_at")),
        processed_at=schemas._iso(row.get("processed_at")),
        body_raw=body_raw,
    )


@router.get("", response_model=schemas.DeviceListResponse)
async def list_devices(
    status_filter: str | None = Query(default=None, alias="status"),
    search: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: auth.AdminUser = Depends(current_admin),
) -> schemas.DeviceListResponse:
    """Daftar device, terbaru dilihat lebih dulu.

    Device yang **belum pernah** dilihat diletakkan paling akhir
    (`last_seen_at IS NULL` diurutkan terpisah) — device `pending` yang belum
    pernah connect tidak perlu menutupi device yang sedang bermasalah.
    """
    total, rows = await fetch(
        queries_devices.list_devices,
        status=status_filter,
        search=search,
        limit=limit,
        offset=offset,
    )
    return schemas.DeviceListResponse(
        total=total, devices=[_device_out(r) for r in rows]
    )


@router.get("/summary")
async def device_summary(
    _: auth.AdminUser = Depends(current_admin),
) -> dict[str, int]:
    """Ringkasan device + kesehatan request 24 jam terakhir."""
    return await fetch(queries_devices.device_health_summary)


@router.get("/{device_id}", response_model=schemas.DeviceOut)
async def get_device(
    device_id: int,
    _: auth.AdminUser = Depends(current_admin),
) -> schemas.DeviceOut:
    row = await fetch(queries_devices.get_device, device_id=device_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Device tidak ditemukan."
        )
    return _device_out(row)


@router.patch("/{device_id}", response_model=schemas.DeviceOut)
async def update_device(
    device_id: int,
    payload: schemas.DeviceUpdateRequest,
    _: auth.AdminUser = Depends(current_admin),
) -> schemas.DeviceOut:
    """Perbarui device. Zona waktu divalidasi sebelum disimpan.

    `tz_name` wajib dicek terhadap `zoneinfo`: nama zona yang salah akan
    membuat seluruh punch device itu bergeser **tanpa error apa pun** — persis
    kegagalan senyap yang paling mahal (SCHEMA §16). Lebih baik menolak di sini
    daripada menemukannya sebulan kemudian.
    """
    if payload.tz_name is not None and not timezones.is_valid_zone(payload.tz_name):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Zona {payload.tz_name!r} tidak dikenali. "
                "Pakai nama IANA seperti 'Asia/Jakarta' (atau alias WIB/WITA/WIT)."
            ),
        )

    # Normalisasi alias (WIB → Asia/Jakarta) sekali saja, lalu pakai hasilnya
    # untuk nama zona maupun cache offset.
    tz_name: str | None = None
    tz_offset: int | None = None
    if payload.tz_name is not None:
        tz_name = timezones.resolve_zone(payload.tz_name).name
        tz_offset = timezones.zone_offset_minutes(tz_name)

    changed = await execute(
        queries_devices.update_device,
        device_id=device_id,
        display_name=payload.display_name,
        location=payload.location,
        status=payload.status,
        tz_name=tz_name,
        tz_offset_minutes=tz_offset,
    )
    if not changed:
        # Tidak ada field yang berubah, atau device tidak ada — bedakan supaya
        # klien tahu apakah permintaannya salah atau memang no-op.
        if await fetch(queries_devices.get_device, device_id=device_id) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Device tidak ditemukan."
            )

    row = await fetch(queries_devices.get_device, device_id=device_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Device tidak ditemukan."
        )
    return _device_out(row)


@router.post("/{device_id}/approve", response_model=schemas.MessageResponse)
async def approve_device(
    device_id: int,
    _: auth.AdminUser = Depends(current_admin),
) -> schemas.MessageResponse:
    """Setujui device `pending` supaya datanya dipercaya."""
    ok = await execute(queries_devices.approve_device, device_id=device_id)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Device tidak ditemukan atau statusnya bukan 'pending'.",
        )
    return schemas.MessageResponse(message="Device disetujui.", id=device_id)


# --- Arsip request --------------------------------------------------------


requests_router = APIRouter(prefix="/requests", tags=["admin:requests"])


@requests_router.get("", response_model=schemas.RequestListResponse)
async def list_requests(
    serial_number: str | None = None,
    table_name: str | None = None,
    process_status: str | None = None,
    since: str | None = Query(
        default=None, description="ISO-8601, mis. 2026-09-30 00:00:00"
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: auth.AdminUser = Depends(current_admin),
) -> schemas.RequestListResponse:
    """Arsip request mentah (tanpa body, agar respons tetap ringan)."""
    total, rows = await fetch(
        queries_devices.list_requests,
        serial_number=serial_number,
        table_name=table_name,
        process_status=process_status,
        since=since,
        limit=limit,
        offset=offset,
    )
    return schemas.RequestListResponse(
        total=total, requests=[_request_out(r) for r in rows]
    )


@requests_router.get("/{request_id}", response_model=schemas.RequestOut)
async def get_request(
    request_id: int,
    _: auth.AdminUser = Depends(current_admin),
) -> schemas.RequestOut:
    """Satu request **beserta body mentahnya**.

    Body dibatasi panjangnya saat dikirim: arsip bisa mencapai 1 MB, dan
    mengirimkannya utuh ke browser untuk sekadar melihat "device mengirim apa"
    itu pemborosan. Pemotongan dilakukan di sini, bukan di query, supaya
    `body_raw` tetap utuh di database.
    """
    row = await fetch(queries_devices.get_request, request_id=request_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Request tidak ditemukan."
        )

    body = row.get("body_raw")
    if isinstance(body, str) and len(body) > 100_000:
        body = body[:100_000] + "\n... (dipotong untuk tampilan)"

    return _request_out(row, body_raw=body)
