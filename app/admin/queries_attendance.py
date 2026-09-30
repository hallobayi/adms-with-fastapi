"""Kueri dashboard: rekap kehadiran harian & koreksi manual.

**Aturan yang menentukan modul ini:** kolom `daily_attendance.is_manual`
(SCHEMA §11) ada supaya koreksi admin tidak ditimpa job olah-ulang otomatis.
Setiap operasi di sini yang menyentuh hasil hitungan wajib menghormatinya:

- Koreksi manual **selalu** menulis `is_manual = 1`.
- Perhitungan ulang **tidak pernah** menyentuh baris yang `is_manual = 1`,
  dan melaporkan berapa baris yang dilewatinya — supaya "kok koreksi saya
  hilang?" tidak pernah terjadi tanpa penjelasan.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from mysql.connector import MySQLConnection

logger = logging.getLogger(__name__)

#: Hari kerja default bila karyawan tidak punya penugasan shift.
DEFAULT_WORK_DAYS = ("MO", "TU", "WE", "TH", "FR")


def list_daily_attendance(
    conn: MySQLConnection,
    *,
    work_date: date | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    employee_id: int | None = None,
    department: str | None = None,
    status: str | None = None,
    only_manual: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> tuple[int, dict[str, int], list[dict[str, object]]]:
    """Rekap kehadiran. Mengembalikan `(total, ringkasan_status, baris)`."""
    where: list[str] = []
    params: list[object] = []

    if work_date is not None:
        where.append("da.work_date = %s")
        params.append(work_date)
    else:
        if date_from is not None:
            where.append("da.work_date >= %s")
            params.append(date_from)
        if date_to is not None:
            where.append("da.work_date <= %s")
            params.append(date_to)

    if employee_id is not None:
        where.append("da.employee_id = %s")
        params.append(employee_id)
    if department:
        where.append("e.department = %s")
        params.append(department)
    if status:
        where.append("da.status = %s")
        params.append(status)
    if only_manual:
        where.append("da.is_manual = 1")

    clause = f"WHERE {' AND '.join(where)}" if where else ""
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))

    with conn.cursor(dictionary=True) as cur:
        # Ringkasan dihitung atas seluruh hasil filter, bukan hanya halaman
        # ini — angka "telat hari ini" tidak berguna kalau hanya separuh.
        #
        # Alias dibungkus backtick: `late` dan `leave` adalah kata kunci MySQL
        # (`LEAVE` mengawali blok stored procedure). Tanpa backtick, `AS leave`
        # adalah galat sintaks 1064 — terbukti menjatuhkan endpoint ini.
        cur.execute(
            f"""
            SELECT COUNT(*) AS total,
                   SUM(da.status = 'present')    AS `present`,
                   SUM(da.status = 'late')       AS `late`,
                   SUM(da.status = 'absent')     AS `absent`,
                   SUM(da.status = 'incomplete') AS `incomplete`,
                   SUM(da.status = 'holiday')    AS `holiday`,
                   SUM(da.status = 'leave')      AS `leave`,
                   SUM(da.late_minutes)          AS `late_minutes_total`,
                   SUM(da.is_manual = 1)         AS `manual`
            FROM daily_attendance da
            JOIN employee e ON e.id = da.employee_id
            {clause}
            """,
            tuple(params),
        )
        agg = cur.fetchone()

        cur.execute(
            f"""
            SELECT da.id, da.employee_id, e.pin, e.name AS employee_name,
                   da.work_date, da.shift_id, s.name AS shift_name,
                   da.first_in, da.last_out, da.punch_count, da.late_minutes,
                   da.early_leave_minutes, da.overtime_minutes, da.worked_minutes,
                   da.status, da.is_manual, da.note
            FROM daily_attendance da
            JOIN employee e ON e.id = da.employee_id
            LEFT JOIN shift s ON s.id = da.shift_id
            {clause}
            ORDER BY da.work_date DESC, e.name
            LIMIT %s OFFSET %s
            """,
            (*params, limit, offset),
        )
        rows = cur.fetchall()

    summary = {
        "present": int(agg["present"] or 0),
        "late": int(agg["late"] or 0),
        "absent": int(agg["absent"] or 0),
        "incomplete": int(agg["incomplete"] or 0),
        "holiday": int(agg["holiday"] or 0),
        "leave": int(agg["leave"] or 0),
        "late_minutes_total": int(agg["late_minutes_total"] or 0),
        "manual": int(agg["manual"] or 0),
    }
    return int(agg["total"] or 0), summary, rows


def correct_daily_attendance(
    conn: MySQLConnection,
    attendance_id: int,
    *,
    status: str | None = None,
    first_in: datetime | None = None,
    last_out: datetime | None = None,
    late_minutes: int | None = None,
    early_leave_minutes: int | None = None,
    overtime_minutes: int | None = None,
    note: str | None = None,
) -> bool:
    """Koreksi manual satu baris kehadiran.

    `is_manual` **selalu** dipaksa menjadi 1 — bukan diserahkan ke pemanggil.
    Itu satu-satunya hal yang mencegah job olah-ulang menimpa koreksi ini,
    jadi menyerahkannya sebagai parameter opsional sama dengan menyediakan
    cara untuk kehilangan koreksi tanpa sadar.
    """
    fields = ["is_manual = 1", "computed_at = NOW()"]
    params: list[object] = []

    for column, value in (
        ("status", status),
        ("first_in", first_in),
        ("last_out", last_out),
        ("late_minutes", late_minutes),
        ("early_leave_minutes", early_leave_minutes),
        ("overtime_minutes", overtime_minutes),
    ):
        if value is not None:
            fields.append(f"{column} = %s")
            params.append(value)

    if note is not None:
        fields.append("note = %s")
        params.append(note)

    params.append(attendance_id)
    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE daily_attendance SET {', '.join(fields)} WHERE id = %s",
            tuple(params),
        )
        return cur.rowcount > 0


def delete_daily_attendance(conn: MySQLConnection, attendance_id: int) -> bool:
    """Hapus satu baris rekap (mis. dibuat keliru). Punch mentah tidak dihapus."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM daily_attendance WHERE id = %s", (attendance_id,))
        return cur.rowcount > 0


# --- Perhitungan ulang ----------------------------------------------------


def _work_day_token(moment: date) -> str:
    return ("MO", "TU", "WE", "TH", "FR", "SA", "SU")[moment.weekday()]


def _shift_for(
    conn: MySQLConnection, employee_id: int, work_date: date
) -> tuple[int | None, dict[str, object] | None]:
    """Cari shift yang berlaku untuk karyawan pada tanggal tertentu.

    Memilih penugasan dengan `effective_from` terbesar yang masih mencakup
    tanggal itu — penugasan terbaru yang menang, bukan yang pertama ditemukan.
    """
    with conn.cursor(dictionary=True) as cur:
        cur.execute(
            """
            SELECT sa.shift_id, sa.work_days,
                   s.name, s.start_time, s.end_time, s.late_tolerance_min,
                   s.early_leave_tol_min, s.is_overnight
            FROM shift_assignment sa
            JOIN shift s ON s.id = sa.shift_id
            WHERE sa.employee_id = %s
              AND sa.effective_from <= %s
              AND (sa.effective_to IS NULL OR sa.effective_to >= %s)
              AND s.is_active = 1
            ORDER BY sa.effective_from DESC, sa.id DESC
            LIMIT 1
            """,
            (employee_id, work_date, work_date),
        )
        row = cur.fetchone()

    if row is None:
        return None, None
    return int(row["shift_id"]), row


def _is_holiday(conn: MySQLConnection, work_date: date) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1 FROM holiday
            WHERE holiday_date = %s
               OR (is_recurring = 1
                   AND MONTH(holiday_date) = MONTH(%s)
                   AND DAY(holiday_date) = DAY(%s))
            LIMIT 1
            """,
            (work_date, work_date, work_date),
        )
        return cur.fetchone() is not None


def recompute_daily(
    conn: MySQLConnection,
    *,
    work_date: date,
    employee_id: int | None = None,
    overwrite_manual: bool = False,
) -> dict[str, int]:
    """Olah ulang `daily_attendance` dari `attendance_log` untuk satu tanggal.

    Punch dikelompokkan per karyawan memakai `punch_date` (tanggal **LOKAL**
    device), bukan tanggal UTC — memakai UTC akan memasukkan punch pagi ke hari
    kerja yang salah (SCHEMA §16).

    Mengembalikan hitungan supaya pemanggil bisa melaporkan apa yang terjadi,
    termasuk berapa baris yang **dilewati** karena dikoreksi manual.
    """
    stats = {"employees": 0, "processed": 0, "created": 0, "updated": 0, "skipped_manual": 0}

    with conn.cursor(dictionary=True) as cur:
        # Karyawan yang punya punch pada tanggal itu.
        cur.execute(
            """
            SELECT DISTINCT a.employee_id
            FROM attendance_log a
            WHERE a.punch_date = %s AND a.employee_id IS NOT NULL
            """ + (" AND a.employee_id = %s" if employee_id is not None else ""),
            (work_date, employee_id) if employee_id is not None else (work_date,),
        )
        employees = [int(r["employee_id"]) for r in cur.fetchall()]

    stats["employees"] = len(employees)
    holiday = _is_holiday(conn, work_date)

    for emp_id in employees:
        # `punch_at_local`, BUKAN `punch_at`. `punch_at` sudah dinormalkan ke
        # UTC, sedangkan `shift.start_time`/`end_time` adalah jam dinding
        # setempat. Membandingkan keduanya langsung membuat shift 08:00 WIB
        # tampak dimulai 6 jam lebih lambat: punch 01:45 UTC (= 08:45 WIB)
        # dihitung "telat 1000 menit". Punch dan shift harus berada di kerangka
        # waktu yang sama — jam dinding device (SCHEMA §16).
        with conn.cursor(dictionary=True) as cur:
            cur.execute(
                """
                SELECT MIN(punch_at_local) AS first_in,
                       MAX(punch_at_local) AS last_out,
                       COUNT(*)            AS punch_count
                FROM attendance_log
                WHERE employee_id = %s AND punch_date = %s
                """,
                (emp_id, work_date),
            )
            agg = cur.fetchone()

        if not agg or agg["punch_count"] == 0:
            continue

        shift_id, shift = _shift_for(conn, emp_id, work_date)
        work_days = (shift or {}).get("work_days")
        day_token = _work_day_token(work_date)

        first_in = agg["first_in"]
        last_out = agg["last_out"]
        punch_count = int(agg["punch_count"])

        status = "present"
        late_minutes = 0
        early_leave = 0
        overtime = 0
        worked = None

        if holiday:
            status = "holiday"
        elif shift is not None and work_days is not None and day_token not in str(work_days):
            # Hari yang tidak dijadwalkan untuk shift ini: karyawan memang tidak
            # diwajibkan masuk, jadi ini bukan "alpa" (absent).
            status = "leave"
        else:
            if punch_count < 2:
                status = "incomplete"
            else:
                worked = int((last_out - first_in).total_seconds() // 60)

            if shift is not None and first_in is not None:
                late_minutes, early_leave, overtime = _compute_shift_deltas(
                    work_date=work_date,
                    first_in=first_in,
                    last_out=last_out,
                    shift=shift,
                )
                if late_minutes > 0:
                    status = "late"

        # Baris yang dikoreksi manual tidak ditimpa, kecuali diminta eksplisit.
        with conn.cursor(dictionary=True) as cur:
            cur.execute(
                "SELECT id, is_manual FROM daily_attendance WHERE employee_id = %s AND work_date = %s",
                (emp_id, work_date),
            )
            existing = cur.fetchone()

        if existing and existing["is_manual"] and not overwrite_manual:
            stats["skipped_manual"] += 1
            continue

        if existing:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE daily_attendance
                    SET shift_id = %s, first_in = %s, last_out = %s,
                        punch_count = %s, late_minutes = %s,
                        early_leave_minutes = %s, overtime_minutes = %s,
                        worked_minutes = %s, status = %s, computed_at = NOW()
                    WHERE id = %s
                    """,
                    (
                        shift_id, first_in, last_out, punch_count, late_minutes,
                        early_leave, overtime, worked, status, existing["id"],
                    ),
                )
            stats["updated"] += 1
        else:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO daily_attendance
                        (employee_id, work_date, shift_id, first_in, last_out,
                         punch_count, late_minutes, early_leave_minutes,
                         overtime_minutes, worked_minutes, status, is_manual)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0)
                    """,
                    (
                        emp_id, work_date, shift_id, first_in, last_out, punch_count,
                        late_minutes, early_leave, overtime, worked, status,
                    ),
                )
            stats["created"] += 1

        stats["processed"] += 1

    return stats


def _compute_shift_deltas(
    *,
    work_date: date,
    first_in: datetime,
    last_out: datetime,
    shift: dict[str, object],
) -> tuple[int, int, int]:
    """Hitung `(late_minutes, early_leave_minutes, overtime_minutes)`.

    Aritmetika memakai `timedelta` Python, **bukan** pengurangan kolom MySQL
    `UNSIGNED` — kolom `late_tolerance_min` sengaja signed untuk alasan yang
    sama: selisih negatif pada kolom UNSIGNED memicu ERROR 1690.
    """
    start: timedelta = shift["start_time"] if isinstance(shift["start_time"], timedelta) else timedelta()
    end: timedelta = shift["end_time"] if isinstance(shift["end_time"], timedelta) else timedelta()
    late_tol = int(shift["late_tolerance_min"] or 0)
    early_tol = int(shift["early_leave_tol_min"] or 0)
    is_overnight = bool(shift["is_overnight"])

    shift_start = datetime.combine(work_date, (datetime.min + start).time())
    shift_end = datetime.combine(work_date, (datetime.min + end).time())
    if is_overnight or end <= start:
        shift_end += timedelta(days=1)

    # Punch bisa sudah lewat tengah malam untuk shift malam.
    check_in = first_in
    check_out = last_out
    if check_in < shift_start - timedelta(hours=6):
        check_in += timedelta(days=1)
    if check_out < check_in:
        check_out += timedelta(days=1)

    late_minutes = max(0, int((check_in - shift_start).total_seconds() // 60) - late_tol)
    early_leave = max(0, int((shift_end - check_out).total_seconds() // 60) - early_tol)
    overtime = max(0, int((check_out - shift_end).total_seconds() // 60))

    return late_minutes, early_leave, overtime


def attendance_summary(conn: MySQLConnection, *, days: int = 1) -> dict[str, int]:
    """Ringkasan kehadiran `days` hari terakhir untuk kepala dashboard."""
    with conn.cursor(dictionary=True) as cur:
        cur.execute(
            """
            SELECT COUNT(*) AS total,
                   SUM(status = 'late') AS `late`,
                   SUM(status = 'absent') AS `absent`,
                   SUM(status = 'incomplete') AS `incomplete`
            FROM daily_attendance
            WHERE work_date >= CURDATE() - INTERVAL %s DAY
            """,
            (max(0, days - 1),),
        )
        row = cur.fetchone()

    return {
        "attendance_total": int(row["total"] or 0),
        "attendance_late": int(row["late"] or 0),
        "attendance_absent": int(row["absent"] or 0),
        "attendance_incomplete": int(row["incomplete"] or 0),
    }