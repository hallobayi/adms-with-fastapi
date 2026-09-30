"""Kueri dashboard: monitoring device & arsip request.

Modul ini sengaja **hanya membaca dan memperbarui** data device — tidak pernah
menyentuh `attendance_log` isinya. Alasannya: satu-satunya peran dashboard di
sini adalah menjawab "device ini kenapa diam?", dan jawabannya ada di status
device + arsip request mentah.
"""

from __future__ import annotations

from mysql.connector import MySQLConnection


def list_devices(
    conn: MySQLConnection,
    *,
    status: str | None = None,
    search: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[int, list[dict[str, object]]]:
    """Daftar device beserta hitungan ringkas. Mengembalikan `(total, baris)`.

    Hitungan diambil lewat subquery berkorelasi, bukan JOIN + GROUP BY, supaya
    tidak mengalikan baris satu sama lain — `attendance_log` bisa jutaan baris
    sementara `device` hanya puluhan.
    """
    where: list[str] = []
    params: list[object] = []

    if status:
        where.append("d.status = %s")
        params.append(status)
    if search:
        where.append("(d.serial_number LIKE %s OR d.display_name LIKE %s OR d.location LIKE %s)")
        pattern = f"%{search}%"
        params.extend([pattern, pattern, pattern])

    clause = f"WHERE {' AND '.join(where)}" if where else ""
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))

    with conn.cursor(dictionary=True) as cur:
        cur.execute(f"SELECT COUNT(*) AS total FROM device d {clause}", tuple(params))
        total = int(cur.fetchone()["total"])

        cur.execute(
            f"""
            SELECT
                d.id, d.serial_number, d.display_name, d.location, d.status,
                d.model, d.firmware, d.ip_address, d.tz_name,
                d.last_seen_at, d.last_handshake_at, d.last_attlog_at, d.created_at,
                (SELECT COUNT(*) FROM attendance_log a WHERE a.device_id = d.id)
                    AS attlog_count,
                (SELECT COUNT(*) FROM command_queue c
                  WHERE c.device_id = d.id AND c.status = 'pending')
                    AS pending_commands,
                (SELECT COUNT(*) FROM attendance_log a
                  WHERE a.device_id = d.id AND a.employee_id IS NULL)
                    AS unlinked_punches
            FROM device d
            {clause}
            ORDER BY (d.last_seen_at IS NULL), d.last_seen_at DESC, d.id DESC
            LIMIT %s OFFSET %s
            """,
            (*params, limit, offset),
        )
        rows = cur.fetchall()

    return total, rows


def get_device(conn: MySQLConnection, device_id: int) -> dict[str, object] | None:
    with conn.cursor(dictionary=True) as cur:
        cur.execute(
            """
            SELECT
                d.id, d.serial_number, d.display_name, d.location, d.status,
                d.model, d.firmware, d.ip_address, d.tz_name,
                d.last_seen_at, d.last_handshake_at, d.last_attlog_at, d.created_at,
                (SELECT COUNT(*) FROM attendance_log a WHERE a.device_id = d.id)
                    AS attlog_count,
                (SELECT COUNT(*) FROM command_queue c
                  WHERE c.device_id = d.id AND c.status = 'pending')
                    AS pending_commands,
                (SELECT COUNT(*) FROM attendance_log a
                  WHERE a.device_id = d.id AND a.employee_id IS NULL)
                    AS unlinked_punches
            FROM device d
            WHERE d.id = %s
            """,
            (device_id,),
        )
        return cur.fetchone()


def update_device(
    conn: MySQLConnection,
    device_id: int,
    *,
    display_name: str | None = None,
    location: str | None = None,
    status: str | None = None,
    tz_name: str | None = None,
    tz_offset_minutes: int | None = None,
) -> bool:
    """Perbarui device. Field `None` tidak diubah.

    `tz_offset_minutes` ditulis bersamaan dengan `tz_name` supaya cache offset
    tidak pernah berbeda dari zona yang jadi sumber kebenarannya.
    """
    fields: list[str] = []
    params: list[object] = []

    if display_name is not None:
        fields.append("display_name = %s")
        params.append(display_name)
    if location is not None:
        fields.append("location = %s")
        params.append(location)
    if status is not None:
        fields.append("status = %s")
        params.append(status)
    if tz_name is not None:
        fields.append("tz_name = %s")
        params.append(tz_name)
        fields.append("tz_offset_minutes = %s")
        params.append(tz_offset_minutes)
        fields.append("last_tz_sync_at = NOW()")

    if not fields:
        return False

    params.append(device_id)
    with conn.cursor() as cur:
        cur.execute(f"UPDATE device SET {', '.join(fields)} WHERE id = %s", tuple(params))
        return cur.rowcount > 0


def approve_device(conn: MySQLConnection, device_id: int) -> bool:
    """Setujui device yang masih `pending` supaya datanya boleh dipercaya.

    Device `pending` tetap **dilayani** handshake-nya (kalau tidak, ia berhenti
    mencoba dan kita kehilangan jejaknya) — persetujuan ini murni soal
    kepercayaan pada data, bukan soal koneksi.
    """
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE device SET status = 'active' WHERE id = %s AND status = 'pending'",
            (device_id,),
        )
        return cur.rowcount > 0


def list_requests(
    conn: MySQLConnection,
    *,
    serial_number: str | None = None,
    table_name: str | None = None,
    process_status: str | None = None,
    since: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[int, list[dict[str, object]]]:
    """Arsip request mentah. `body_raw` **tidak** diambil di sini.

    Body bisa mencapai 1 MB per baris; mengambilnya untuk daftar 50 baris akan
    memindahkan puluhan MB hanya agar kolomnya tidak terlihat. Detail satu
    request punya endpoint sendiri.
    """
    where: list[str] = []
    params: list[object] = []

    if serial_number:
        where.append("serial_number = %s")
        params.append(serial_number)
    if table_name:
        where.append("table_name = %s")
        params.append(table_name)
    if process_status:
        where.append("process_status = %s")
        params.append(process_status)
    if since:
        where.append("created_at >= %s")
        params.append(since)

    clause = f"WHERE {' AND '.join(where)}" if where else ""
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))

    with conn.cursor(dictionary=True) as cur:
        cur.execute(f"SELECT COUNT(*) AS total FROM iclock_request {clause}", tuple(params))
        total = int(cur.fetchone()["total"])

        cur.execute(
            f"""
            SELECT id, device_id, serial_number, endpoint, http_method, table_name,
                   body_bytes, line_count, parsed_count, stored_count, dup_count,
                   failed_count, process_status, error_message, source_ip,
                   created_at, processed_at
            FROM iclock_request
            {clause}
            ORDER BY id DESC
            LIMIT %s OFFSET %s
            """,
            (*params, limit, offset),
        )
        rows = cur.fetchall()

    return total, rows


def get_request(conn: MySQLConnection, request_id: int) -> dict[str, object] | None:
    """Satu request **beserta body mentahnya**."""
    with conn.cursor(dictionary=True) as cur:
        cur.execute(
            """
            SELECT id, device_id, serial_number, endpoint, http_method, table_name,
                   c_param, stamp, op_stamp, query_string, content_type,
                   body_raw, body_bytes, line_count, parsed_count, stored_count,
                   dup_count, failed_count, response_body, process_status,
                   error_message, source_ip, user_agent, created_at, processed_at
            FROM iclock_request
            WHERE id = %s
            """,
            (request_id,),
        )
        return cur.fetchone()


def device_health_summary(conn: MySQLConnection) -> dict[str, int]:
    """Ringkasan cepat untuk kepala dashboard."""
    with conn.cursor(dictionary=True) as cur:
        cur.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(status = 'active')    AS active,
                SUM(status = 'pending')   AS pending,
                SUM(status = 'suspended') AS suspended,
                SUM(last_seen_at IS NULL) AS never_seen
            FROM device
            """
        )
        devices = cur.fetchone()

        cur.execute(
            """
            SELECT
                SUM(process_status = 'failed')   AS failed,
                SUM(process_status = 'received') AS stuck,
                SUM(dup_count > 0)               AS with_duplicates
            FROM iclock_request
            WHERE created_at >= NOW() - INTERVAL 24 HOUR
            """
        )
        requests = cur.fetchone()

    return {
        "devices_total": int(devices["total"] or 0),
        "devices_active": int(devices["active"] or 0),
        "devices_pending": int(devices["pending"] or 0),
        "devices_suspended": int(devices["suspended"] or 0),
        "devices_never_seen": int(devices["never_seen"] or 0),
        "requests_failed_24h": int(requests["failed"] or 0),
        "requests_stuck_24h": int(requests["stuck"] or 0),
        "requests_with_duplicates_24h": int(requests["with_duplicates"] or 0),
    }
