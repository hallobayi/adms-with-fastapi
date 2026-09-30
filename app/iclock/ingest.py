"""Orkestrasi penanganan request device: arsipkan, parse, simpan, balas.

Dipisah dari router supaya alur ini bisa diuji tanpa HTTP, dan supaya aturan
pentingnya terlihat di satu tempat:

**Arsipkan lebih dulu, parse kemudian.** Body mentah ditulis ke
`iclock_request` *sebelum* diparse. Kalau parser salah membaca sesuatu, data
aslinya masih ada dan bisa diproses ulang setelah parser diperbaiki — tanpa
arsip ini, satu bug parser berarti data yang tidak bisa dipulihkan.

**Kegagalan tidak boleh menghentikan device.** Bila penyimpanan gagal, kita
tetap menjawab `OK`. Device tidak punya konsep "coba lagi nanti karena server
sedang sibuk" — ia hanya akan mengulang, dan itu memperburuk keadaan.
"""

from __future__ import annotations

import logging

from app.config import get_settings
from app.database import connection
from app.iclock import parser, protocol, store, timezones

logger = logging.getLogger(__name__)

#: Batas jumlah perintah per respons `getrequest`.
COMMANDS_PER_RESPONSE = 20


def handle_handshake(
    *,
    serial_number: str,
    query_params: dict[str, str],
    body: str,
    source_ip: str | None = None,
    user_agent: str | None = None,
) -> dict[str, object]:
    """Tangani handshake: catat device, perbarui last-seen, siapkan respons.

    Handshake tetap diarsipkan karena justru pada momen inilah kita bisa
    melihat device sebenarnya mengirim parameter apa — berguna sekali saat
    device "connect tapi tidak mengirim data".
    """
    info: dict[str, object] = {"serial_number": serial_number, "status": None}

    try:
        with connection() as conn:
            device_id, status, tz_name = store.get_or_create_device(
                conn, serial_number, ip_address=source_ip
            )
            request_id = store.record_request(
                conn,
                serial_number=serial_number,
                endpoint="cdata",
                http_method="GET",
                query_params=query_params,
                content_type=None,
                body=body,
                source_ip=source_ip,
                user_agent=user_agent,
                device_id=device_id,
            )
            store.mark_handshake(conn, device_id, int(query_params.get("OpStamp", 0) or 0))
            store.finalize_request(
                conn, request_id, status="processed", response="handshake"
            )
            conn.commit()

            info["device_id"] = device_id
            info["status"] = status
            info["tz_name"] = tz_name

            if status == "pending":
                logger.info(
                    "Device %s handshake — status masih 'pending', "
                    "menunggu persetujuan admin",
                    serial_number,
                )
    except Exception:  # noqa: BLE001 — handshake harus tetap dibalas
        logger.exception("Gagal mencatat handshake SN=%s", serial_number)

    return info


def handle_records(
    *,
    serial_number: str,
    query_params: dict[str, str],
    body: str,
    source_ip: str | None = None,
    user_agent: str | None = None,
) -> int:
    """Tangani unggahan data. Mengembalikan jumlah baris yang **dikirim** device."""
    # Body dipisah SEKALI. Sebelumnya pemisahan yang sama dijalankan tiga kali
    # untuk satu request (di sini, di `record_request`, dan di `parse_*`) — pada
    # batch ribuan baris itu pekerjaan yang murni berulang.
    lines = parser.split_lines(body)
    sent = len(lines)

    if sent == 0:
        # Body kosong tetap dicatat: device yang melakukan ini biasanya sedang
        # "menandai" posisi, dan polanya berguna untuk diagnosis.
        _archive_only(
            serial_number, query_params, body, source_ip, user_agent, status="skipped"
        )
        return 0

    table = query_params.get("table")
    kind = protocol.table_kind(table)
    # Dihitung sekali; dipakai untuk kolom arsip tanpa perlu mengulang
    # pemisahan/`encode` di dalam `record_request`.
    body_bytes = len(body.encode("utf-8"))
    settings = get_settings()

    try:
        with connection() as conn:
            # `touch_attlog` digabung ke UPDATE device yang sama dengan
            # `last_seen_at`, sehingga unggahan ATTLOG tidak lagi menulis dua
            # kali ke baris device yang sama dalam satu request.
            device_id, device_status, device_tz = store.get_or_create_device(
                conn,
                serial_number,
                ip_address=source_ip,
                touch_attlog=kind == "attendance",
            )
            request_id = store.record_request(
                conn,
                serial_number=serial_number,
                endpoint="cdata",
                http_method="POST",
                query_params=query_params,
                content_type=None,
                body=body,
                source_ip=source_ip,
                user_agent=user_agent,
                device_id=device_id,
                line_count=sent,
                body_bytes=body_bytes,
            )

            zone = timezones.resolve_zone(device_tz, settings.default_tz_name)
            if zone.is_fallback and kind == "attendance":
                # Dicatat sebagai anomali: artinya device ini zonanya belum
                # dikonfigurasi, dan seluruh punch-nya berpotensi bergeser.
                logger.warning(
                    "SN=%s memakai zona cadangan %s (%s) — punch berisiko bergeser",
                    serial_number,
                    zone.name,
                    zone.source,
                )

            parsed = stored = duplicates = failed = 0

            if kind == "biometric":
                parsed, stored, failed = _ingest_biometric(
                    conn, device_id=device_id, lines=lines
                )
            elif kind == "userinfo":
                parsed, stored, failed = _ingest_userinfo(
                    conn, device_id=device_id, lines=lines
                )
            else:
                parsed, stored, duplicates = _ingest_attendance(
                    conn,
                    device_id=device_id,
                    serial_number=serial_number,
                    lines=lines,
                    zone_name=zone.name,
                    request_id=request_id,
                )

            store.finalize_request(
                conn,
                request_id,
                status="processed" if failed == 0 else "partial",
                parsed=parsed,
                stored=stored,
                duplicates=duplicates,
                failed=failed,
                response=f"OK: {sent}",
            )
            conn.commit()

            logger.info(
                "SN=%s table=%s: dikirim=%d parsed=%d disimpan=%d dup=%d gagal=%d",
                serial_number,
                table,
                sent,
                parsed,
                stored,
                duplicates,
                failed,
            )
    except Exception:  # noqa: BLE001
        logger.exception("Gagal memproses unggahan SN=%s", serial_number)
        _archive_only(
            serial_number,
            query_params,
            body,
            source_ip,
            user_agent,
            status="failed",
            error="handler exception",
        )

    return sent


def _ingest_attendance(
    conn,
    *,
    device_id: int,
    serial_number: str,
    lines: list[str],
    zone_name: str,
    request_id: int,
) -> tuple[int, int, int]:
    """Parse & simpan ATTLOG. Mengembalikan `(parsed, stored, duplicates)`."""
    records = parser.parse_attendance_lines(lines)
    if not records:
        return 0, 0, 0

    stored, duplicates = store.store_attendance(
        conn,
        device_id=device_id,
        serial_number=serial_number,
        records=records,
        zone_name=zone_name,
        request_id=request_id,
    )

    # Isi employee_id untuk PIN yang sudah terdaftar. Punch dengan PIN belum
    # dikenal dibiarkan NULL (tidak dibuang). Dibatasi pada baris milik request
    # ini supaya tidak memindai seluruh tabel yang belum tertaut.
    store.link_employee_pins(conn, [r.pin for r in records], request_id=request_id)

    return len(records), stored, duplicates


def _ingest_biometric(conn, *, device_id: int, lines: list[str]) -> tuple[int, int, int]:
    """Simpan user + template dari OPERLOG. Mengembalikan `(parsed, stored, failed)`."""
    users = parser.parse_users_lines(lines)
    fingerprints = parser.parse_fingerprint_lines(lines)

    stored = 0
    failed = 0

    if users:
        stored += store.store_device_users(conn, device_id=device_id, records=users)

    if fingerprints:
        saved = store.upsert_fingerprints(
            conn, device_id=device_id, serial_number="", records=fingerprints
        )
        stored += saved
        failed += len(fingerprints) - saved

    return len(users) + len(fingerprints), stored, failed


def _ingest_userinfo(conn, *, device_id: int, lines: list[str]) -> tuple[int, int, int]:
    """Simpan data user dari `table=USERINFO`."""
    users = parser.parse_users_lines(lines)
    if not users:
        return 0, 0, 0
    stored = store.store_device_users(conn, device_id=device_id, records=users)
    return len(users), stored, 0


def _archive_only(
    serial_number: str,
    query_params: dict[str, str],
    body: str,
    source_ip: str | None,
    user_agent: str | None,
    *,
    status: str,
    error: str | None = None,
) -> None:
    """Arsipkan body tanpa memprosesnya.

    Dipakai untuk body kosong dan untuk jalur penyelamatan saat pemrosesan
    gagal — yang penting body-nya tidak hilang.
    """
    try:
        with connection() as conn:
            device_id, _, _ = store.get_or_create_device(
                conn, serial_number, ip_address=source_ip
            )
            request_id = store.record_request(
                conn,
                serial_number=serial_number,
                endpoint="cdata",
                http_method="POST",
                query_params=query_params,
                content_type=None,
                body=body,
                source_ip=source_ip,
                user_agent=user_agent,
                device_id=device_id,
            )
            store.finalize_request(
                conn, request_id, status=status, error=error, response="archived"
            )
            conn.commit()
    except Exception:  # noqa: BLE001 — jalur penyelamatan, jangan melempar lagi
        logger.exception("Gagal mengarsipkan body SN=%s", serial_number)


def take_commands(serial_number: str) -> list[str]:
    """Ambil perintah pending untuk device dan tandai sudah dikirim."""
    try:
        with connection() as conn:
            device_id, _, _ = store.get_or_create_device(conn, serial_number)
            rows = store.pending_commands(
                conn, device_id, limit=COMMANDS_PER_RESPONSE
            )
            if not rows:
                return []
            store.mark_commands_sent(conn, [command_id for command_id, _ in rows])
            conn.commit()
            return [command_text for _, command_text in rows]
    except Exception:  # noqa: BLE001
        logger.exception("Gagal mengambil perintah untuk SN=%s", serial_number)
        return []


def handle_command_acks(*, serial_number: str, body: str) -> int:
    """Terapkan konfirmasi perintah dari device."""
    acks = parser.parse_command_acks(body)
    if not acks:
        logger.info("SN=%s devicecmd tanpa ack yang bisa diparse", serial_number)
        return 0

    try:
        with connection() as conn:
            applied = store.apply_command_acks(
                conn, acks, serial_number=serial_number, raw_response=body
            )
            conn.commit()
            return applied
    except Exception:  # noqa: BLE001
        logger.exception("Gagal menerapkan ack SN=%s", serial_number)
        return 0


def touch(serial_number: str) -> None:
    """Perbarui `last_seen_at` device."""
    try:
        with connection() as conn:
            device_id, _, _ = store.get_or_create_device(conn, serial_number)
            store.touch_device(conn, device_id)
            conn.commit()
    except Exception:  # noqa: BLE001
        logger.exception("Gagal memperbarui last_seen SN=%s", serial_number)
