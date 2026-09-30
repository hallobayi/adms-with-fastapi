"""Penulisan data iClock ke database.

Modul ini adalah satu-satunya tempat yang tahu bagaimana punch, user, dan
template masuk ke tabel. Pemisahan ini penting karena aturan idempotensi di
sini halus: device memang mengirim ulang batch yang sama setiap kali jaringan
putus, dan itu bukan kesalahan — server harus menanganinya tanpa menggandakan
baris.

Prinsip yang dipegang:

- **Body mentah selalu diarsipkan dulu** ke `iclock_request`, sebelum diparse.
  Ini yang memungkinkan memperbaiki parser lalu memproses ulang data lama.
- **`record_hash` memakai waktu LOKAL**, bukan UTC. Kalau memakai UTC, koreksi
  `device.tz_name` di kemudian hari akan mengubah hash dan menggandakan seluruh
  absensi (lihat SCHEMA §5).
- **Balasan selalu `OK: <jumlah yang DIKIRIM>`,** bukan jumlah yang disimpan.
  Device memakai angka itu sebagai penanda posisi unggahan; memberi angka yang
  lebih kecil membuatnya mengirim ulang batch yang sama selamanya.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime

from mysql.connector import MySQLConnection

from app.iclock import parser, protocol, timezones

logger = logging.getLogger(__name__)

#: Batas ukuran body mentah yang disimpan (karakter). Body yang lebih besar
#: dipotong supaya satu request aneh tidak menghabiskan storage.
MAX_BODY_CHARS = 1_000_000


@dataclass
class IngestResult:
    """Ringkasan satu batch yang ditangani."""

    parsed: int = 0
    stored: int = 0
    duplicates: int = 0
    failed: int = 0
    request_id: int | None = None
    warnings: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.warnings is None:
            self.warnings = []


def compute_record_hash(
    serial_number: str,
    pin: str,
    punch_at_local: datetime,
    status_code: int | None,
    verify_mode: int | None,
    work_code: int | None,
) -> str:
    """Hitung SHA-1 identitas sebuah punch.

    Memakai `punch_at_local` dengan sengaja (lihat docstring modul). `Stamp`
    device tidak ikut di-hash karena perilakunya berbeda antar firmware.
    """
    parts = [
        serial_number or "",
        pin or "",
        punch_at_local.strftime("%Y-%m-%d %H:%M:%S"),
        "" if status_code is None else str(status_code),
        "" if verify_mode is None else str(verify_mode),
        "" if work_code is None else str(work_code),
    ]
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()


def record_request(
    conn: MySQLConnection,
    *,
    serial_number: str,
    endpoint: str,
    http_method: str,
    query_params: dict[str, str],
    content_type: str | None,
    body: str,
    source_ip: str | None = None,
    user_agent: str | None = None,
    device_id: int | None = None,
    line_count: int | None = None,
    body_bytes: int | None = None,
) -> int:
    """Arsipkan satu request apa adanya. Mengembalikan `iclock_request.id`.

    Dipanggil untuk **setiap** request, termasuk handshake — justru pada saat
    device "tidak mengirim apa-apa" arsip inilah yang menunjukkan device
    sebenarnya bicara apa.

    `line_count` dan `body_bytes` boleh diberikan pemanggil yang **sudah**
    menghitungnya: pemisahan baris dan `encode()` atas body yang sama tidak
    perlu diulang dua kali untuk satu request (lihat `ingest.handle_records`).
    """
    table_name = query_params.get("table")
    truncated = body[:MAX_BODY_CHARS] if body else None

    if line_count is None:
        line_count = len(parser.split_lines(body))
    if body_bytes is None:
        body_bytes = len(body.encode("utf-8")) if body else 0

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO iclock_request
                (device_id, serial_number, endpoint, http_method, table_name,
                 c_param, stamp, op_stamp, query_string, content_type,
                 body_raw, body_bytes, line_count, source_ip, user_agent,
                 process_status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'received')
            """,
            (
                device_id,
                serial_number,
                endpoint,
                http_method,
                table_name,
                query_params.get("c"),
                query_params.get("Stamp"),
                query_params.get("OpStamp"),
                _encode_query(query_params),
                content_type,
                truncated,
                body_bytes,
                line_count,
                source_ip,
                user_agent,
            ),
        )
        request_id = cur.lastrowid

    return int(request_id)


def _encode_query(params: dict[str, str]) -> str | None:
    if not params:
        return None
    return "&".join(f"{k}={v}" for k, v in params.items())[:1024]


def finalize_request(
    conn: MySQLConnection,
    request_id: int,
    *,
    status: str,
    parsed: int = 0,
    stored: int = 0,
    duplicates: int = 0,
    failed: int = 0,
    response: str | None = None,
    error: str | None = None,
) -> None:
    """Tutup satu baris `iclock_request` dengan hasil pemrosesannya."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE iclock_request
            SET process_status = %s, parsed_count = %s, stored_count = %s,
                dup_count = %s, failed_count = %s, response_body = %s,
                error_message = %s, processed_at = NOW()
            WHERE id = %s
            """,
            (status, parsed, stored, duplicates, failed, response, error, request_id),
        )


# --- Absensi --------------------------------------------------------------


def store_attendance(
    conn: MySQLConnection,
    *,
    device_id: int | None,
    serial_number: str,
    records: list[parser.AttendanceRecord],
    zone_name: str,
    request_id: int | None = None,
) -> tuple[int, int]:
    """Simpan punch. Mengembalikan `(tersimpan, duplikat)`.

    Idempotensi bertumpu pada `UNIQUE KEY uk_attlog_hash`; pengiriman ulang
    device menjadi tidak berbahaya tanpa perlu mengecek duplikat lebih dulu.

    Seluruh baris batch dikirim lewat **satu `executemany`**. Sebelumnya tiap
    record memakai `execute` sendiri, artinya satu perjalanan bolak-balik ke
    MySQL per punch — pada batch beberapa ribu baris itu perbedaan yang sangat
    terasa pada latensi request.
    """
    if not records:
        return 0, 0

    params: list[tuple[object, ...]] = []
    for record in records:
        punch_at = timezones.to_utc(record.punch_at_local, zone_name)
        # Tanggal diambil dari waktu LOKAL: punch 06:00 WIB adalah 23:00 UTC
        # hari sebelumnya, dan memakai tanggal UTC akan memasukkan punch
        # pagi ke hari kerja yang salah.
        punch_date = record.punch_at_local.date()
        record_hash = compute_record_hash(
            serial_number,
            record.pin,
            record.punch_at_local,
            record.status_code,
            record.verify_mode,
            record.work_code,
        )
        params.append(
            (
                device_id,
                serial_number,
                record.pin,
                punch_at,
                record.punch_at_local,
                zone_name,
                punch_date,
                record.status_code,
                record.verify_mode,
                record.work_code,
                json.dumps(record.reserved) if record.reserved else None,
                record_hash,
                record.raw_line[:512],
                record.format_variant,
                request_id,
            )
        )

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO attendance_log
                (device_id, serial_number, pin, punch_at, punch_at_local,
                 tz_applied, punch_date, status_code, verify_mode, work_code,
                 reserved_fields, record_hash, raw_line, format_variant,
                 parse_status, iclock_request_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    'ok', %s)
            ON DUPLICATE KEY UPDATE id = id
            """,
            params,
        )
        # `executemany` tidak melaporkan pernyataan mana yang menyisipkan dan
        # mana yang kena `ON DUPLICATE KEY`, jadi `rowcount` dipakai sebagai
        # angka tersimpan dan sisanya dihitung sebagai duplikat. Perlu
        # diingat: `cursor.rowcount` setelah `executemany` di mysql-connector
        # mengembalikan jumlah **baris** yang terpengaruh (bukan jumlah
        # statement), jadi `min()` di bawah menjaga nilainya tetap waras.
        stored = min(int(cur.rowcount or 0), len(params))
        duplicates = len(params) - stored

    return stored, duplicates


# --- Data user ------------------------------------------------------------


def store_device_users(
    conn: MySQLConnection,
    *,
    device_id: int,
    records: list[parser.UserRecord],
) -> int:
    """Simpan/cerminkan user yang dilaporkan device ke `device_user`."""
    if not records:
        return 0

    rows = [
        (
            device_id,
            record.pin,
            record.name,
            record.privilege,
            record.card_no,
            record.password,
            record.group_id,
            record.raw_line[:512],
        )
        for record in records
    ]

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO device_user
                (device_id, pin, name, privilege, card_no, password, group_id,
                 last_seen_at, raw_line, sync_status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), %s, 'in_sync')
            ON DUPLICATE KEY UPDATE
                name = VALUES(name),
                privilege = VALUES(privilege),
                card_no = VALUES(card_no),
                password = VALUES(password),
                group_id = VALUES(group_id),
                last_seen_at = NOW(),
                raw_line = VALUES(raw_line)
            """,
            rows,
        )

    return len(rows)


def link_employee_pins(
    conn: MySQLConnection,
    pins: list[str],
    *,
    request_id: int | None = None,
) -> int:
    """Isi `attendance_log.employee_id` untuk PIN yang sudah punya karyawan.

    Punch yang PIN-nya belum dikenal dibiarkan `NULL` (bukan dibuang!) supaya
    bisa dicocokkan setelah data karyawan dilengkapi.

    Bila `request_id` diberikan, pencarian dibatasi pada baris yang **baru
    saja** ditulis oleh request ini (`iclock_request_id`). Tanpa batas itu,
    setiap unggahan ATTLOG memindai seluruh `attendance_log` yang sudah
    `employee_id IS NULL` — biayanya tumbuh terus seiring tabel bertambah,
    padahal baris lama sudah tidak bisa berubah lagi di sini. `NULL` tetap
    diizinkan (dipakai jalur pemanggilan lain yang memang ingin menyapu
    seluruh tabel), dan `idx_attlog_request` menopang pemfilteran ini.
    """
    unique_pins = sorted({pin for pin in pins if pin})
    if not unique_pins:
        return 0

    placeholders = ", ".join(["%s"] * len(unique_pins))
    scope = " AND a.iclock_request_id = %s" if request_id is not None else ""
    params: tuple[object, ...] = tuple(unique_pins)
    if request_id is not None:
        params = (*unique_pins, request_id)

    with conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE attendance_log a
            JOIN employee e ON e.pin = a.pin
            SET a.employee_id = e.id
            WHERE a.employee_id IS NULL AND a.pin IN ({placeholders}){scope}
            """,
            params,
        )
        return int(cur.rowcount)


def upsert_fingerprints(
    conn: MySQLConnection,
    *,
    device_id: int,
    serial_number: str,
    records: list[parser.FingerprintRecord],
) -> int:
    """Simpan template sidik jari sebagai salinan milik device.

    Baris di sini adalah **salinan di device** (`device_id` terisi), bukan
    template master. Membedakan keduanya adalah syarat sinkronisasi dua arah:
    tanpa itu kita tidak bisa tahu sebuah template berasal dari device mana.

    Blob disimpan utuh, dan `template_sha256` dihitung atas byte **mentah**
    hasil dekode base64 — bukan atas string base64-nya — supaya hash tetap
    sama bila ada device lain mengirim template yang sama dengan padding
    berbeda.
    """
    import hashlib

    rows = []
    for record in records:
        blob = parser.decode_template(record.template)
        if not blob:
            continue
        rows.append(
            (
                device_id,
                record.pin,
                record.finger_index,
                hashlib.sha256(blob).hexdigest(),
                len(blob),
            )
        )

    if not rows:
        return 0

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO finger_template
                (device_id, pin, finger_index, object_key, template_sha256,
                 content_type, byte_size, upload_state, version, source,
                 sync_state, last_pulled_at)
            VALUES (%s, %s, %s, NULL, %s, 'application/octet-stream', %s,
                    'pending', 1, 'device', 'pending_pull', NOW())
            ON DUPLICATE KEY UPDATE
                template_sha256 = VALUES(template_sha256),
                byte_size = VALUES(byte_size),
                last_pulled_at = NOW()
            """,
            rows,
        )

    return len(rows)


# --- Device ---------------------------------------------------------------


def get_or_create_device(
    conn: MySQLConnection,
    serial_number: str,
    *,
    ip_address: str | None = None,
    touch_attlog: bool = False,
) -> tuple[int | None, str, str | None]:
    """Cari device berdasarkan SN, buat bila belum ada.

    Mengembalikan `(device_id, status, tz_name)`.

    Device baru dibuat dengan `status='pending'` — dan **tetap dilayani** saat
    handshake. Kalau tidak dilayani, device berhenti mencoba dan kita tidak
    akan pernah tahu ia ada. Yang belum dipercaya hanya *datanya*, bukan
    *koneksinya*.

    `touch_attlog=True` ikut memperbarui `last_attlog_at` dalam UPDATE yang
    sama. Ini menghilangkan satu round-trip terpisah per unggahan ATTLOG —
    nilainya jarang dibaca, jadi menumpangkannya gratis.
    """
    with conn.cursor(dictionary=True) as cur:
        cur.execute(
            "SELECT id, status, tz_name FROM device WHERE serial_number = %s",
            (serial_number,),
        )
        row = cur.fetchone()

        if row:
            cur.execute(
                f"""
                UPDATE device
                SET last_seen_at = NOW(),
                    ip_address = COALESCE(%s, ip_address)
                    {", last_attlog_at = NOW()" if touch_attlog else ""}
                WHERE id = %s
                """,
                (ip_address, row["id"]),
            )
            return int(row["id"]), row["status"], row["tz_name"]

        cur.execute(
            """
            INSERT INTO device
                (serial_number, status, ip_address, last_seen_at, last_attlog_at)
            VALUES (%s, 'pending', %s, NOW(), %s)
            """,
            (serial_number, ip_address, datetime.now() if touch_attlog else None),
        )
        new_id = int(cur.lastrowid)

    logger.info("Device baru terdaftar: SN=%s (status=pending)", serial_number)
    return new_id, "pending", None


def mark_handshake(conn: MySQLConnection, device_id: int, op_stamp: int) -> None:
    """Catat bahwa handshake sudah dilayani."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE device
            SET last_handshake_at = NOW(), last_seen_at = NOW(),
                stamp_version = %s
            WHERE id = %s
            """,
            (op_stamp, device_id),
        )


def touch_device(conn: MySQLConnection, device_id: int) -> None:
    """Perbarui `last_seen_at` saja."""
    with conn.cursor() as cur:
        cur.execute("UPDATE device SET last_seen_at = NOW() WHERE id = %s", (device_id,))


def mark_attlog(conn: MySQLConnection, device_id: int) -> None:
    """Catat punch terakhir yang diterima dari device ini."""
    with conn.cursor() as cur:
        cur.execute("UPDATE device SET last_attlog_at = NOW() WHERE id = %s", (device_id,))


# --- Perintah -------------------------------------------------------------


def next_command_id(conn: MySQLConnection) -> int:
    """Ambil ID perintah berikutnya (naik monoton, unik lintas device).

    ID ini bagian dari wire protocol (`C:<id>:<cmd>`), jadi ia **tidak** boleh
    memakai `AUTO_INCREMENT` tabel: device bisa mengenali ulang ID yang sama
    setelah server restart, dan konfirmasinya akan dikaitkan ke perintah yang
    salah.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT COALESCE(MAX(command_id), 0) + 1 FROM command_queue")
        row = cur.fetchone()
    return int(row[0]) if row else 1


def next_command_ids(conn: MySQLConnection, count: int) -> list[int]:
    """Ambil `count` ID perintah berikutnya dalam **satu** kueri.

    Dipakai saat mengantrikan banyak perintah sekaligus (mis. penarikan
    sidik jari). Memanggil `next_command_id()` per perintah berarti satu
    kueri `MAX()` per baris — dan karena pemanggil belum melakukan INSERT,
    loop seperti itu bahkan tidak melihat baris yang baru saja ia susun.
    """
    if count <= 0:
        return []
    start = next_command_id(conn)
    return list(range(start, start + count))


def queue_command(
    conn: MySQLConnection,
    *,
    device_id: int,
    payload: str,
    command_type: str,
    requested_by: int | None = None,
) -> int:
    """Antrikan satu perintah untuk device. Mengembalikan `command_id`."""
    command_id = next_command_id(conn)
    command_text = protocol.frame(command_id, payload)

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO command_queue
                (command_id, device_id, command_text, command_type, status,
                 requested_by)
            VALUES (%s, %s, %s, %s, 'pending', %s)
            """,
            (command_id, device_id, command_text, command_type, requested_by),
        )

    return command_id


def queue_commands(
    conn: MySQLConnection,
    *,
    device_id: int,
    payloads: list[tuple[str, str]],
    requested_by: int | None = None,
) -> list[int]:
    """Antrikan banyak perintah sekaligus. Mengembalikan daftar `command_id`.

    `payloads` berisi pasangan `(payload, command_type)`. Seluruh ID dialokasikan
    dalam satu kueri (`next_command_ids`) dan seluruh baris disisipkan dengan
    satu `executemany`, alih-alih satu kueri `MAX()` + satu INSERT per perintah.
    Ini yang membuat penarikan sidik jari (ratusan perintah) tidak lagi menjadi
    ratusan round-trip.
    """
    if not payloads:
        return []

    ids = next_command_ids(conn, len(payloads))
    rows = [
        (command_id, device_id, protocol.frame(command_id, payload), command_type,
         requested_by)
        for command_id, (payload, command_type) in zip(ids, payloads)
    ]

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO command_queue
                (command_id, device_id, command_text, command_type, status,
                 requested_by)
            VALUES (%s, %s, %s, %s, 'pending', %s)
            """,
            rows,
        )

    return ids


def pending_commands(
    conn: MySQLConnection,
    device_id: int,
    *,
    limit: int = 20,
) -> list[tuple[int, str]]:
    """Ambil perintah `pending` untuk device, siap dikirim.

    Dibatasi jumlahnya: penarikan sidik jari bisa mengantrikan ratusan perintah,
    dan menyerahkannya sekaligus dalam satu respons adalah cara cepat membuat
    device tersedak. Device akan kembali beberapa detik lagi kok.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT command_id, command_text
            FROM command_queue
            WHERE device_id = %s
              AND status = 'pending'
              AND (expires_at IS NULL OR expires_at > NOW())
            ORDER BY command_id
            LIMIT %s
            """,
            (device_id, max(1, limit)),
        )
        rows = cur.fetchall()

    return [(int(row[0]), row[1]) for row in rows]


def mark_commands_sent(conn: MySQLConnection, command_ids: list[int]) -> None:
    """Tandai perintah sudah diserahkan ke device (menunggu konfirmasi)."""
    if not command_ids:
        return
    placeholders = ", ".join(["%s"] * len(command_ids))
    with conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE command_queue
            SET status = 'sent', sent_at = NOW(),
                attempt_count = attempt_count + 1
            WHERE command_id IN ({placeholders}) AND status = 'pending'
            """,
            tuple(command_ids),
        )


def apply_command_acks(
    conn: MySQLConnection,
    acks: list[tuple[int, int]],
    *,
    serial_number: str,
    raw_response: str | None = None,
) -> int:
    """Terapkan konfirmasi device. Mengembalikan jumlah ack yang dikenali.

    `Return=0` berarti sukses; selain itu error (mis. `-1004` = tabel/fitur
    tidak didukung model). Mencatat ini yang mengubah "kami sudah mengantrikan
    penarikan sidik jari" menjadi "device menerima/menolaknya" — tanpa ini hal
    tersebut tidak terlihat sama sekali.
    """
    applied = 0

    with conn.cursor() as cur:
        for command_id, return_code in acks:
            succeeded = return_code == protocol.RETURN_OK
            cur.execute(
                """
                UPDATE command_queue
                SET status = %s,
                    acked_at = NOW(),
                    return_code = %s,
                    response_raw = %s,
                    error_message = CASE WHEN %s THEN error_message
                                         ELSE CONCAT('Device menolak dengan Return=', %s)
                                    END
                WHERE command_id = %s AND status IN ('pending', 'sent')
                """,
                (
                    "acked" if succeeded else "failed",
                    return_code,
                    (raw_response or "")[:1024] or None,
                    1 if succeeded else 0,
                    return_code,
                    command_id,
                ),
            )
            if cur.rowcount:
                applied += 1
                logger.info(
                    "Ack device SN=%s command_id=%s return=%s ok=%s",
                    serial_number,
                    command_id,
                    return_code,
                    succeeded,
                )

    return applied


def requeue_stuck_commands(conn: MySQLConnection, *, timeout_minutes: int = 15) -> int:
    """Kembalikan perintah yang tidak dikonfirmasi ke `pending`.

    Tanpa ini, satu device yang mati di tengah jalan akan meninggalkan
    perintahnya berstatus `sent` selamanya, dan perintah itu tidak akan pernah
    dikirim lagi.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE command_queue
            SET status = CASE WHEN attempt_count >= max_attempts THEN 'failed'
                              ELSE 'pending' END,
                error_message = CONCAT('Tidak dikonfirmasi device dalam ',
                                       %s, ' menit')
            WHERE status = 'sent'
              AND sent_at IS NOT NULL
              AND sent_at < NOW() - INTERVAL %s MINUTE
            """,
            (timeout_minutes, timeout_minutes),
        )
        return int(cur.rowcount)
