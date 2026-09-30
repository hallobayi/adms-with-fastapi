"""Skema request/response untuk dashboard admin (`/api/admin/*`).

Nama field sengaja memakai `snake_case` yang sama dengan kolom database supaya
pemetaannya jelas dan tidak ada kejutan saat membaca query. Semua waktu
dikirim sebagai string ISO-8601; nilai `datetime` dari MySQL tidak memiliki
info zona, dan mengirimnya sebagai tipe OpenAPI tertentu akan menyesatkan
(browser akan menafsirkan zona secara berbeda-beda).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


def _iso(value: Any) -> str | None:
    """Serialisasi datetime/date ke ISO-8601, `None` tetap `None`."""
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat(sep=" ") if isinstance(value, datetime) else value.isoformat()
    return str(value)


# --- Auth -----------------------------------------------------------------


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=1024)


class AdminMe(BaseModel):
    """Identitas admin yang sedang login."""

    id: int
    username: str
    display_name: str | None = None
    is_superuser: bool


class LoginResponse(BaseModel):
    admin: AdminMe
    expires_at: str | None = None


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=8, max_length=1024)


class AdminCreateRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    password: str = Field(min_length=8, max_length=1024)
    display_name: str | None = Field(default=None, max_length=128)
    is_superuser: bool = False


class AdminUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=128)
    is_active: bool | None = None
    is_superuser: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=1024)


# --- Monitoring device ----------------------------------------------------


class DeviceOut(BaseModel):
    id: int
    serial_number: str
    display_name: str | None = None
    location: str | None = None
    status: str
    model: str | None = None
    firmware: str | None = None
    ip_address: str | None = None
    tz_name: str | None = None
    last_seen_at: str | None = None
    last_handshake_at: str | None = None
    last_attlog_at: str | None = None
    created_at: str | None = None
    attlog_count: int = 0
    pending_commands: int = 0
    unlinked_punches: int = 0


class DeviceListResponse(BaseModel):
    total: int
    devices: list[DeviceOut]


class DeviceUpdateRequest(BaseModel):
    """Perubahan yang boleh dilakukan admin terhadap device.

    `tz_name` ikut di sini karena salah zona adalah penyebab pergeseran jam
    yang paling sering dan tidak memunculkan error apa pun (SCHEMA §16).
    `serial_number` **tidak** bisa diubah: itu identitas device di lapangan.
    """

    display_name: str | None = Field(default=None, max_length=128)
    location: str | None = Field(default=None, max_length=191)
    status: Literal["pending", "active", "suspended"] | None = None
    tz_name: str | None = Field(default=None, max_length=64)


class RequestOut(BaseModel):
    """Satu baris arsip `iclock_request`."""

    id: int
    device_id: int | None = None
    serial_number: str
    endpoint: str
    http_method: str
    table_name: str | None = None
    body_bytes: int = 0
    line_count: int = 0
    parsed_count: int = 0
    stored_count: int = 0
    dup_count: int = 0
    failed_count: int = 0
    process_status: str
    error_message: str | None = None
    source_ip: str | None = None
    created_at: str | None = None
    processed_at: str | None = None
    body_raw: str | None = Field(
        default=None,
        description="Hanya diisi pada detail satu request; pada daftar dibiarkan null.",
    )


class RequestListResponse(BaseModel):
    total: int
    requests: list[RequestOut]


# --- Konflik sinkronisasi -------------------------------------------------


class ConflictOut(BaseModel):
    id: int
    device_id: int | None = None
    serial_number: str
    entity_type: str
    pin: str | None = None
    finger_index: int | None = None
    action: str
    conflict_detail: str | None = None
    resolved_by: str
    created_at: str | None = None


class ConflictListResponse(BaseModel):
    total: int
    conflicts: list[ConflictOut]


class ConflictResolveRequest(BaseModel):
    """Keputusan admin atas satu konflik.

    Keputusan #3: konflik **selalu** ditinjau manual, jadi hanya ada dua arah
    yang bermakna — pakai versi server, atau pakai versi device. Tidak ada
    mode "otomatis" yang boleh memilih sendiri.
    """

    resolution: Literal["server_wins", "device_wins"]
    note: str | None = Field(
        default=None,
        max_length=255,
        description="Alasan keputusan; ikut tercatat di sync_log untuk audit.",
    )


class ConflictResolveResponse(BaseModel):
    conflict_id: int
    resolution: str
    affected: int = 0
    message: str


# --- Absensi --------------------------------------------------------------


class DailyAttendanceOut(BaseModel):
    id: int
    employee_id: int
    pin: str | None = None
    employee_name: str | None = None
    work_date: str
    shift_id: int | None = None
    shift_name: str | None = None
    first_in: str | None = None
    last_out: str | None = None
    punch_count: int = 0
    late_minutes: int = 0
    early_leave_minutes: int = 0
    overtime_minutes: int = 0
    worked_minutes: int | None = None
    status: str
    is_manual: bool = False
    note: str | None = None


class DailyAttendanceListResponse(BaseModel):
    total: int
    summary: dict[str, int]
    attendance: list[DailyAttendanceOut]


class AttendanceCorrectRequest(BaseModel):
    """Koreksi manual satu baris kehadiran.

    `is_manual` **selalu** diset 1 oleh server saat endpoint ini dipakai.
    Tanpa itu, job olah-ulang berikutnya akan menimpa koreksi admin dengan
    hitungan otomatis dari punch — persis yang dicegah kolom itu (SCHEMA §11).
    """

    status: Literal["present", "late", "absent", "incomplete", "holiday", "leave"] | None = None
    first_in: datetime | None = None
    last_out: datetime | None = None
    late_minutes: int | None = Field(default=None, ge=0)
    early_leave_minutes: int | None = Field(default=None, ge=0)
    overtime_minutes: int | None = Field(default=None, ge=0)
    note: str | None = Field(default=None, max_length=255)


class RecomputeResponse(BaseModel):
    work_date: str
    employees: int = 0
    processed: int = 0
    created: int = 0
    updated: int = 0
    skipped_manual: int = 0


# --- CRUD data master -----------------------------------------------------


class EmployeeOut(BaseModel):
    id: int
    pin: str
    name: str
    employee_code: str | None = None
    department: str | None = None
    position: str | None = None
    email: str | None = None
    phone: str | None = None
    joined_at: str | None = None
    resigned_at: str | None = None
    is_active: bool = True


class EmployeeListResponse(BaseModel):
    total: int
    employees: list[EmployeeOut]


class EmployeeCreateRequest(BaseModel):
    pin: str = Field(min_length=1, max_length=24)
    name: str = Field(min_length=1, max_length=128)
    employee_code: str | None = Field(default=None, max_length=32)
    department: str | None = Field(default=None, max_length=64)
    position: str | None = Field(default=None, max_length=64)
    email: str | None = Field(default=None, max_length=128)
    phone: str | None = Field(default=None, max_length=32)
    joined_at: date | None = None
    is_active: bool = True


class EmployeeUpdateRequest(BaseModel):
    pin: str | None = Field(default=None, min_length=1, max_length=24)
    name: str | None = Field(default=None, min_length=1, max_length=128)
    employee_code: str | None = Field(default=None, max_length=32)
    department: str | None = Field(default=None, max_length=64)
    position: str | None = Field(default=None, max_length=64)
    email: str | None = Field(default=None, max_length=128)
    phone: str | None = Field(default=None, max_length=32)
    joined_at: date | None = None
    resigned_at: date | None = None
    is_active: bool | None = None


class ShiftOut(BaseModel):
    id: int
    name: str
    start_time: str
    end_time: str
    late_tolerance_min: int = 0
    early_leave_tol_min: int = 0
    is_overnight: bool = False
    is_active: bool = True


class ShiftListResponse(BaseModel):
    total: int
    shifts: list[ShiftOut]


class ShiftCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    start_time: str = Field(pattern=r"^\d{2}:\d{2}(:\d{2})?$")
    end_time: str = Field(pattern=r"^\d{2}:\d{2}(:\d{2})?$")
    late_tolerance_min: int = Field(default=0, ge=0, le=1440)
    early_leave_tol_min: int = Field(default=0, ge=0, le=1440)
    is_overnight: bool = False
    is_active: bool = True


class ShiftUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    start_time: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}(:\d{2})?$")
    end_time: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}(:\d{2})?$")
    late_tolerance_min: int | None = Field(default=None, ge=0, le=1440)
    early_leave_tol_min: int | None = Field(default=None, ge=0, le=1440)
    is_overnight: bool | None = None
    is_active: bool | None = None


class ShiftAssignmentOut(BaseModel):
    id: int
    employee_id: int
    pin: str | None = None
    employee_name: str | None = None
    shift_id: int
    shift_name: str | None = None
    effective_from: str
    effective_to: str | None = None
    work_days: list[str] = []


class ShiftAssignmentListResponse(BaseModel):
    total: int
    assignments: list[ShiftAssignmentOut]


class ShiftAssignmentCreateRequest(BaseModel):
    employee_id: int
    shift_id: int
    effective_from: date
    effective_to: date | None = None
    work_days: list[Literal["MO", "TU", "WE", "TH", "FR", "SA", "SU"]] = Field(
        default_factory=lambda: ["MO", "TU", "WE", "TH", "FR"]
    )


class HolidayOut(BaseModel):
    id: int
    holiday_date: str
    name: str
    is_recurring: bool = False


class HolidayListResponse(BaseModel):
    total: int
    holidays: list[HolidayOut]


class HolidayCreateRequest(BaseModel):
    holiday_date: date
    name: str = Field(min_length=1, max_length=128)
    is_recurring: bool = False


class MessageResponse(BaseModel):
    """Balasan sederhana untuk operasi tulis."""

    ok: bool = True
    message: str
    id: int | None = None
