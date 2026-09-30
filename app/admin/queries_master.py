"""Kueri dashboard: CRUD data master (karyawan, shift, penugasan, hari libur).

Dua hal yang menentukan bentuk modul ini:

- **`employee.pin` adalah jembatan ke device.** `link_employee_pins` mencocokkan
  `attendance_log.pin` ke `employee.pin`, jadi mengubah PIN seorang karyawan
  berarti memutus tautan punch lama miliknya. Karena itu perubahan PIN
  dilaporkan jumlah punch yang tidak lagi tertaut — bukan dibiarkan senyap.
- **`shift_assignment` memakai UNIQUE (employee_id, shift_id, effective_from)**
  sehingga penugasan ganda pada tanggal mulai yang sama ditolak database, bukan
  hanya oleh validasi aplikasi.
"""

from __future__ import annotations

import logging
from datetime import date

from mysql.connector import MySQLConnection

logger = logging.getLogger(__name__)

#: Urutan kanonik hari kerja, dipakai untuk menormalkan `SET(...)` MySQL.
_WORK_DAY_ORDER = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")


def _normalize_work_days(days: list[str] | None) -> str | None:
    """Ubah daftar hari menjadi bentuk `SET` MySQL ('MO,TU,...').

    Nilai di luar daftar dibuang dan urutannya diseragamkan supaya
    perbandingan string konsisten.
    """
    if days is None:
        return None
    seen = {d.upper() for d in days}
    ordered = [d for d in _WORK_DAY_ORDER if d in seen]
    return ",".join(ordered) if ordered else "MO,TU,WE,TH,FR"


# --- Karyawan -------------------------------------------------------------


def list_employees(
    conn: MySQLConnection,
    *,
    search: str | None = None,
    department: str | None = None,
    is_active: bool | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[int, list[dict[str, object]]]:
    where: list[str] = []
    params: list[object] = []

    if search:
        where.append("(pin LIKE %s OR name LIKE %s OR employee_code LIKE %s)")
        pattern = f"%{search}%"
        params.extend([pattern, pattern, pattern])
    if department:
        where.append("department = %s")
        params.append(department)
    if is_active is not None:
        where.append("is_active = %s")
        params.append(1 if is_active else 0)

    clause = f"WHERE {' AND '.join(where)}" if where else ""
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))

    with conn.cursor(dictionary=True) as cur:
        cur.execute(f"SELECT COUNT(*) AS total FROM employee {clause}", tuple(params))
        total = int(cur.fetchone()["total"])

        cur.execute(
            f"""
            SELECT id, pin, name, employee_code, department, position, email, phone,
                   joined_at, resigned_at, is_active
            FROM employee
            {clause}
            ORDER BY is_active DESC, name
            LIMIT %s OFFSET %s
            """,
            (*params, limit, offset),
        )
        rows = cur.fetchall()

    return total, rows


def get_employee(conn: MySQLConnection, employee_id: int) -> dict[str, object] | None:
    with conn.cursor(dictionary=True) as cur:
        cur.execute(
            """
            SELECT id, pin, name, employee_code, department, position, email, phone,
                   joined_at, resigned_at, is_active
            FROM employee WHERE id = %s
            """,
            (employee_id,),
        )
        return cur.fetchone()


def create_employee(conn: MySQLConnection, **fields: object) -> int:
    columns = [
        "pin", "name", "employee_code", "department", "position",
        "email", "phone", "joined_at", "is_active",
    ]
    values = [fields.get(c) for c in columns]
    is_active = fields.get("is_active")
    values[-1] = 1 if is_active is None else (1 if is_active else 0)

    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO employee ({', '.join(columns)})
            VALUES ({', '.join(['%s'] * len(columns))})
            """,
            tuple(values),
        )
        return int(cur.lastrowid)


def update_employee(conn: MySQLConnection, employee_id: int, **fields: object) -> dict[str, int]:
    """Perbarui karyawan. Mengembalikan `{updated, unlinked, relinked}`.

    Bila `pin` berubah, punch lama yang menunjuk PIN lama tidak lagi cocok
    dengan karyawan ini. Kita **tidak** menulis ulang `attendance_log` secara
    diam-diam — punch adalah data mentah dari device dan mengubahnya berarti
    memalsukan jejak. Yang dilakukan: menghitung berapa yang jadi tidak tertaut
    supaya bisa dilaporkan ke admin.
    """
    allowed = (
        "pin", "name", "employee_code", "department", "position",
        "email", "phone", "joined_at", "resigned_at", "is_active",
    )
    result = {"updated": 0, "unlinked": 0, "relinked": 0}

    old_pin: str | None = None
    new_pin = fields.get("pin")
    if new_pin is not None:
        with conn.cursor(dictionary=True) as cur:
            cur.execute("SELECT pin FROM employee WHERE id = %s", (employee_id,))
            row = cur.fetchone()
        if row is not None:
            old_pin = row["pin"]

    set_parts: list[str] = []
    params: list[object] = []
    for column in allowed:
        if column in fields and fields[column] is not None:
            set_parts.append(f"{column} = %s")
            value = fields[column]
            if column == "is_active":
                value = 1 if value else 0
            params.append(value)

    if not set_parts:
        return result

    params.append(employee_id)
    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE employee SET {', '.join(set_parts)} WHERE id = %s", tuple(params)
        )
        result["updated"] = int(cur.rowcount)

    if old_pin is not None and new_pin is not None and str(new_pin) != str(old_pin):
        with conn.cursor() as cur:
            # Punch lama yang tadinya milik karyawan ini: putuskan tautannya.
            cur.execute(
                """
                UPDATE attendance_log
                SET employee_id = NULL
                WHERE employee_id = %s AND pin = %s
                """,
                (employee_id, old_pin),
            )
            result["unlinked"] = int(cur.rowcount)

            # Punch yang kebetulan sudah memakai PIN baru: taungkan sekarang.
            cur.execute(
                """
                UPDATE attendance_log
                SET employee_id = %s
                WHERE employee_id IS NULL AND pin = %s
                """,
                (employee_id, new_pin),
            )
            result["relinked"] = int(cur.rowcount)

        logger.info(
            "PIN karyawan %s diubah %s -> %s: %s punch diputus, %s ditautkan ulang",
            employee_id, old_pin, new_pin, result["unlinked"], result["relinked"],
        )

    return result


def delete_employee(conn: MySQLConnection, employee_id: int) -> bool:
    """Hapus karyawan. Punch-nya tetap ada dengan `employee_id = NULL`.

    FK memakai `ON DELETE SET NULL` untuk alasan ini: menghapus seorang
    karyawan tidak boleh menghapus bukti kehadirannya.
    """
    with conn.cursor() as cur:
        cur.execute("DELETE FROM employee WHERE id = %s", (employee_id,))
        return cur.rowcount > 0


# --- Shift ----------------------------------------------------------------


def list_shifts(
    conn: MySQLConnection, *, is_active: bool | None = None
) -> list[dict[str, object]]:
    where, params = "", []
    if is_active is not None:
        where = "WHERE is_active = %s"
        params.append(1 if is_active else 0)

    with conn.cursor(dictionary=True) as cur:
        cur.execute(
            f"""
            SELECT id, name, start_time, end_time, late_tolerance_min,
                   early_leave_tol_min, is_overnight, is_active
            FROM shift {where}
            ORDER BY is_active DESC, name
            """,
            tuple(params),
        )
        return cur.fetchall()


def get_shift(conn: MySQLConnection, shift_id: int) -> dict[str, object] | None:
    with conn.cursor(dictionary=True) as cur:
        cur.execute(
            """
            SELECT id, name, start_time, end_time, late_tolerance_min,
                   early_leave_tol_min, is_overnight, is_active
            FROM shift WHERE id = %s
            """,
            (shift_id,),
        )
        return cur.fetchone()


def create_shift(conn: MySQLConnection, **fields: object) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO shift
                (name, start_time, end_time, late_tolerance_min,
                 early_leave_tol_min, is_overnight, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                fields.get("name"),
                fields.get("start_time"),
                fields.get("end_time"),
                fields.get("late_tolerance_min", 0),
                fields.get("early_leave_tol_min", 0),
                1 if fields.get("is_overnight") else 0,
                1 if fields.get("is_active", True) else 0,
            ),
        )
        return int(cur.lastrowid)


def update_shift(conn: MySQLConnection, shift_id: int, **fields: object) -> bool:
    allowed = (
        "name", "start_time", "end_time", "late_tolerance_min",
        "early_leave_tol_min", "is_overnight", "is_active",
    )
    set_parts: list[str] = []
    params: list[object] = []
    for column in allowed:
        if column in fields and fields[column] is not None:
            value = fields[column]
            if column in ("is_overnight", "is_active"):
                value = 1 if value else 0
            set_parts.append(f"{column} = %s")
            params.append(value)

    if not set_parts:
        return False

    params.append(shift_id)
    with conn.cursor() as cur:
        cur.execute(f"UPDATE shift SET {', '.join(set_parts)} WHERE id = %s", tuple(params))
        return cur.rowcount > 0


def delete_shift(conn: MySQLConnection, shift_id: int) -> tuple[bool, str]:
    """Hapus shift. Ditolak bila masih dipakai penugasan (FK RESTRICT).

    Pesannya menyebut jumlah penugasan yang menghalangi — "gagal" saja tidak
    memberi tahu admin apa yang harus dibersihkan lebih dulu.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM shift_assignment WHERE shift_id = %s", (shift_id,)
        )
        used = int(cur.fetchone()[0])

    if used:
        return False, (
            f"Shift masih dipakai oleh {used} penugasan. "
            "Cabut penugasannya lebih dulu."
        )

    with conn.cursor() as cur:
        cur.execute("DELETE FROM shift WHERE id = %s", (shift_id,))
        if cur.rowcount == 0:
            return False, "Shift tidak ditemukan."
    return True, "Shift dihapus."


# --- Penugasan shift ------------------------------------------------------


def list_shift_assignments(
    conn: MySQLConnection,
    *,
    employee_id: int | None = None,
    shift_id: int | None = None,
    active_on: date | None = None,
    limit: int = 200,
    offset: int = 0,
) -> tuple[int, list[dict[str, object]]]:
    where: list[str] = []
    params: list[object] = []

    if employee_id is not None:
        where.append("sa.employee_id = %s")
        params.append(employee_id)
    if shift_id is not None:
        where.append("sa.shift_id = %s")
        params.append(shift_id)
    if active_on is not None:
        where.append("sa.effective_from <= %s")
        params.append(active_on)
        where.append("(sa.effective_to IS NULL OR sa.effective_to >= %s)")
        params.append(active_on)

    clause = f"WHERE {' AND '.join(where)}" if where else ""
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))

    with conn.cursor(dictionary=True) as cur:
        cur.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM shift_assignment sa {clause}
            """,
            tuple(params),
        )
        total = int(cur.fetchone()["total"])

        cur.execute(
            f"""
            SELECT sa.id, sa.employee_id, e.pin, e.name AS employee_name,
                   sa.shift_id, s.name AS shift_name,
                   sa.effective_from, sa.effective_to, sa.work_days
            FROM shift_assignment sa
            JOIN employee e ON e.id = sa.employee_id
            JOIN shift s ON s.id = sa.shift_id
            {clause}
            ORDER BY sa.effective_from DESC, e.name
            LIMIT %s OFFSET %s
            """,
            (*params, limit, offset),
        )
        rows = cur.fetchall()

    return total, rows


def create_shift_assignment(conn: MySQLConnection, **fields: object) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO shift_assignment
                (employee_id, shift_id, effective_from, effective_to, work_days)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                fields.get("employee_id"),
                fields.get("shift_id"),
                fields.get("effective_from"),
                fields.get("effective_to"),
                _normalize_work_days(fields.get("work_days")),  # type: ignore[arg-type]
            ),
        )
        return int(cur.lastrowid)


def delete_shift_assignment(conn: MySQLConnection, assignment_id: int) -> bool:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM shift_assignment WHERE id = %s", (assignment_id,))
        return cur.rowcount > 0


# --- Hari libur -----------------------------------------------------------


def list_holidays(
    conn: MySQLConnection,
    *,
    year: int | None = None,
    limit: int = 200,
    offset: int = 0,
) -> tuple[int, list[dict[str, object]]]:
    where, params = "", []
    if year is not None:
        where = "WHERE YEAR(holiday_date) = %s OR is_recurring = 1"
        params.append(year)

    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))

    with conn.cursor(dictionary=True) as cur:
        cur.execute(f"SELECT COUNT(*) AS total FROM holiday {where}", tuple(params))
        total = int(cur.fetchone()["total"])

        cur.execute(
            f"""
            SELECT id, holiday_date, name, is_recurring
            FROM holiday {where}
            ORDER BY holiday_date DESC
            LIMIT %s OFFSET %s
            """,
            (*params, limit, offset),
        )
        rows = cur.fetchall()

    return total, rows


def create_holiday(conn: MySQLConnection, **fields: object) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO holiday (holiday_date, name, is_recurring)
            VALUES (%s, %s, %s)
            """,
            (
                fields.get("holiday_date"),
                fields.get("name"),
                1 if fields.get("is_recurring") else 0,
            ),
        )
        return int(cur.lastrowid)


def delete_holiday(conn: MySQLConnection, holiday_id: int) -> bool:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM holiday WHERE id = %s", (holiday_id,))
        return cur.rowcount > 0


def distinct_departments(conn: MySQLConnection) -> list[str]:
    """Daftar departemen unik, untuk mengisi filter di klien."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT department FROM employee
            WHERE department IS NOT NULL AND department <> ''
            ORDER BY department
            """
        )
        return [row[0] for row in cur.fetchall()]
