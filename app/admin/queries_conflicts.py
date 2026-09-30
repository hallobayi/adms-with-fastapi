"""Kueri dashboard: konflik sinkronisasi dua arah.

**Aturan yang tidak boleh dilanggar (keputusan #3):** konflik **selalu**
ditinjau manual. Tidak ada jalur otomatis yang memilih pemenang — taruhannya
karyawan harus merekam ulang sidik jarinya, dan itu keputusan manusia.

Konsekuensi yang terlihat di modul ini:

- Tidak ada fungsi "auto-resolve" atau "resolusi termuda menang".
- Menyelesaikan konflik menulis jejaknya ke `sync_log` (`resolved_by`), bukan
  menghapus barisnya. Baris yang kalah di-`is_valid=0` pada `finger_template`,
  bukan di-DELETE — jejak audit harus tetap ada.
"""

from __future__ import annotations

import logging

from mysql.connector import MySQLConnection

logger = logging.getLogger(__name__)


def list_conflicts(
    conn: MySQLConnection,
    *,
    serial_number: str | None = None,
    entity_type: str | None = None,
    resolved: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[int, list[dict[str, object]]]:
    """Antrean konflik yang perlu ditinjau admin.

    `resolved=False` (default dari endpoint) menampilkan hanya yang
    `resolved_by = 'none'` — itulah antrean kerja yang sebenarnya.
    """
    where: list[str] = []
    params: list[object] = []

    if resolved is None or resolved is False:
        where.append("resolved_by = 'none'")
    elif resolved is True:
        where.append("resolved_by <> 'none'")

    if serial_number:
        where.append("serial_number = %s")
        params.append(serial_number)
    if entity_type:
        where.append("entity_type = %s")
        params.append(entity_type)

    # Predikat tetap `outcome = 'conflict'` dibangun sekali saja, lalu filter
    # tambahan disambung — supaya jumlah placeholder `%s` selalu sepadan
    # dengan jumlah parameter.
    conditions = ["outcome = 'conflict'", *where]
    clause = " AND ".join(conditions)
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))

    with conn.cursor(dictionary=True) as cur:
        cur.execute(f"SELECT COUNT(*) AS total FROM sync_log WHERE {clause}", tuple(params))
        total = int(cur.fetchone()["total"])

        cur.execute(
            f"""
            SELECT id, device_id, serial_number, entity_type, pin, finger_index,
                   action, conflict_detail, resolved_by, command_id, created_at
            FROM sync_log
            WHERE {clause}
            ORDER BY id DESC
            LIMIT %s OFFSET %s
            """,
            (*params, limit, offset),
        )
        rows = cur.fetchall()

    return total, rows


def get_conflict(conn: MySQLConnection, conflict_id: int) -> dict[str, object] | None:
    with conn.cursor(dictionary=True) as cur:
        cur.execute(
            """
            SELECT id, device_id, serial_number, entity_type, pin, finger_index,
                   action, outcome, conflict_detail, resolved_by, command_id, created_at
            FROM sync_log
            WHERE id = %s
            """,
            (conflict_id,),
        )
        return cur.fetchone()


def resolve_conflict(
    conn: MySQLConnection,
    conflict_id: int,
    *,
    resolution: str,
    note: str | None = None,
) -> tuple[bool, str, int]:
    """Terapkan keputusan admin. Mengembalikan `(diterapkan, pesan, terdampak)`.

    Untuk konflik **template sidik jari**, keputusan ini diterjemahkan menjadi
    penonaktifan baris yang kalah:

    - `server_wins` → salinan milik device (`device_id IS NOT NULL`) di-set
      `is_valid = 0`, lalu master ditandai perlu dikirim ulang ke device.
    - `device_wins` → master (`device_id IS NULL`) di-set `is_valid = 0`, dan
      salinan device dinaikkan menjadi sumber kebenaran.

    Baris **tidak pernah dihapus**. Bila ternyata keputusannya keliru, jejaknya
    masih ada untuk ditelusuri.
    """
    if resolution not in {"server_wins", "device_wins"}:
        return False, f"Resolusi {resolution!r} tidak dikenal.", 0

    conflict = get_conflict(conn, conflict_id)
    if conflict is None:
        return False, f"Konflik {conflict_id} tidak ditemukan.", 0
    if conflict["outcome"] != "conflict":
        return False, f"Baris {conflict_id} bukan konflik.", 0
    if conflict["resolved_by"] != "none":
        return False, f"Konflik {conflict_id} sudah diselesaikan sebelumnya.", 0

    pin = conflict["pin"]
    finger_index = conflict["finger_index"]
    device_id = conflict["device_id"]
    entity_type = conflict["entity_type"]
    affected = 0

    if entity_type == "finger_template" and pin is not None and finger_index is not None:
        affected = _resolve_finger_conflict(
            conn,
            pin=pin,
            finger_index=finger_index,
            device_id=device_id,
            resolution=resolution,
        )
    elif entity_type == "user":
        # Konflik user diselesaikan dengan menyelaraskan `device_user` ke sisi
        # yang dipilih; pengiriman ulang ke device terjadi lewat command_queue
        # yang diantrikan terpisah agar tidak ada tulis ganda di satu transaksi.
        affected = _resolve_user_conflict(
            conn,
            pin=pin,
            device_id=device_id,
            resolution=resolution,
        )

    detail = conflict["conflict_detail"] or ""
    if note:
        detail = f"{detail} | {note}" if detail else note

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE sync_log
            SET resolved_by = %s,
                conflict_detail = %s
            WHERE id = %s
            """,
            (resolution, detail[:255], conflict_id),
        )

    return True, f"Konflik {conflict_id} diselesaikan ({resolution}).", affected


def _resolve_finger_conflict(
    conn: MySQLConnection,
    *,
    pin: str,
    finger_index: int,
    device_id: int | None,
    resolution: str,
) -> int:
    """Nonaktifkan sisi yang kalah pada `finger_template`. Mengembalikan jumlah baris."""
    if resolution == "server_wins":
        # Salinan milik device kalah; master dipertahankan.
        cond, params = "device_id IS NOT NULL", [pin, finger_index]
        if device_id is not None:
            cond = "device_id = %s"
            params = [pin, finger_index, device_id]
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE finger_template
                SET is_valid = 0,
                    sync_state = 'conflict'
                WHERE pin = %s AND finger_index = %s AND {cond} AND is_valid = 1
                """,
                tuple(params),
            )
            lost = cur.rowcount

            # Master ditandai perlu didorong ulang ke device.
            cur.execute(
                """
                UPDATE finger_template
                SET sync_state = 'pending_push'
                WHERE pin = %s AND finger_index = %s
                  AND device_id IS NULL AND is_valid = 1
                """,
                (pin, finger_index),
            )
        return int(lost)

    # device_wins: master kalah, salinan device jadi acuan.
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE finger_template
            SET is_valid = 0,
                sync_state = 'conflict'
            WHERE pin = %s AND finger_index = %s
              AND device_id IS NULL AND is_valid = 1
            """,
            (pin, finger_index),
        )
        lost = cur.rowcount

        cur.execute(
            """
            UPDATE finger_template
            SET sync_state = 'in_sync'
            WHERE pin = %s AND finger_index = %s
              AND device_id IS NOT NULL AND is_valid = 1
            """,
            (pin, finger_index),
        )
    return int(lost)


def _resolve_user_conflict(
    conn: MySQLConnection,
    *,
    pin: str | None,
    device_id: int | None,
    resolution: str,
) -> int:
    """Tandai `device_user` sesuai keputusan."""
    if pin is None:
        return 0

    new_status = "in_sync" if resolution == "server_wins" else "device_only"
    with conn.cursor() as cur:
        if device_id is not None:
            cur.execute(
                """
                UPDATE device_user
                SET sync_status = %s
                WHERE pin = %s AND device_id = %s
                """,
                (new_status, pin, device_id),
            )
        else:
            cur.execute(
                "UPDATE device_user SET sync_status = %s WHERE pin = %s",
                (new_status, pin),
            )
        return int(cur.rowcount)


def conflict_summary(conn: MySQLConnection) -> dict[str, int]:
    """Hitungan cepat untuk lencana notifikasi di dashboard."""
    with conn.cursor(dictionary=True) as cur:
        cur.execute(
            """
            SELECT
                SUM(resolved_by = 'none')  AS unresolved,
                SUM(resolved_by <> 'none') AS resolved
            FROM sync_log
            WHERE outcome = 'conflict'
            """
        )
        row = cur.fetchone()

    return {
        "conflicts_unresolved": int(row["unresolved"] or 0),
        "conflicts_resolved": int(row["resolved"] or 0),
    }
