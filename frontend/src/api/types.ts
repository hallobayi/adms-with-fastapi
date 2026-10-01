/**
 * Bentuk data dari `app/admin/schemas.py`, ditulis ulang untuk TypeScript.
 *
 * Berkas ini adalah cermin, bukan sumber kebenaran: kalau sebuah model Pydantic
 * berubah, tipe di sini harus ikut berubah. Bedanya sengaja dibuat sesedikit
 * mungkin (nama field sama persis) supaya perbedaannya langsung terlihat saat
 * membaca.
 *
 * Catatan: seluruh waktu dari server berupa **string** yang sudah diformat
 * server (`schemas._iso`), bukan objek Date — jadi tidak ada parsing implisit
 * yang bisa menggeser zona waktu.
 */

// --- Auth -----------------------------------------------------------------

export interface AdminMe {
  id: number
  username: string
  display_name: string | null
  is_superuser: boolean
}

export interface LoginResponse {
  admin: AdminMe
  expires_at: string | null
}

export interface AdminCreateRequest {
  username: string
  password: string
  display_name?: string | null
  is_superuser?: boolean
}

export interface AdminUpdateRequest {
  display_name?: string | null
  is_active?: boolean | null
  is_superuser?: boolean | null
  password?: string | null
}

// --- Umum -----------------------------------------------------------------

export interface MessageResponse {
  ok: boolean
  message: string
  id?: number | null
}

export interface AccountOut {
  id: number
  username: string
  display_name: string | null
  is_active: boolean
  is_superuser: boolean
  last_login_at: string | null
  created_at: string | null
}

export interface AccountListResponse {
  total: number
  accounts: AccountOut[]
}

// --- Device ---------------------------------------------------------------

export type DeviceStatus = 'pending' | 'active' | 'suspended'

export interface DeviceOut {
  id: number
  serial_number: string
  display_name: string | null
  location: string | null
  status: DeviceStatus
  model: string | null
  firmware: string | null
  ip_address: string | null
  tz_name: string | null
  last_seen_at: string | null
  last_handshake_at: string | null
  last_attlog_at: string | null
  created_at: string | null
  attlog_count: number
  pending_commands: number
  unlinked_punches: number
}

export interface DeviceListResponse {
  total: number
  devices: DeviceOut[]
}

export interface DeviceUpdateRequest {
  display_name?: string | null
  location?: string | null
  status?: DeviceStatus | null
  tz_name?: string | null
}

// --- Arsip request --------------------------------------------------------

export interface RequestOut {
  id: number
  device_id: number | null
  serial_number: string
  endpoint: string
  http_method: string
  table_name: string | null
  body_bytes: number
  line_count: number
  parsed_count: number
  stored_count: number
  dup_count: number
  failed_count: number
  process_status: string
  error_message: string | null
  source_ip: string | null
  created_at: string | null
  processed_at: string | null
  body_raw?: string | null
}

export interface RequestListResponse {
  total: number
  requests: RequestOut[]
}

// --- Konflik --------------------------------------------------------------

export type ConflictResolution = 'server_wins' | 'device_wins'

export interface ConflictOut {
  id: number
  device_id: number | null
  serial_number: string
  entity_type: string
  pin: string | null
  finger_index: number | null
  action: string
  conflict_detail: string | null
  resolved_by: string
  created_at: string | null
}

export interface ConflictListResponse {
  total: number
  conflicts: ConflictOut[]
}

export interface ConflictResolveRequest {
  resolution: ConflictResolution
  note?: string | null
}

export interface ConflictResolveResponse {
  conflict_id: number
  resolution: string
  affected: number
  message: string
}

// --- Kehadiran ------------------------------------------------------------

export type AttendanceStatus =
  | 'present'
  | 'late'
  | 'absent'
  | 'incomplete'
  | 'holiday'
  | 'leave'

export interface DailyAttendanceOut {
  id: number
  employee_id: number
  pin: string | null
  employee_name: string | null
  work_date: string
  shift_id: number | null
  shift_name: string | null
  first_in: string | null
  last_out: string | null
  punch_count: number
  late_minutes: number
  early_leave_minutes: number
  overtime_minutes: number
  worked_minutes: number | null
  status: AttendanceStatus
  is_manual: boolean
  note: string | null
}

export interface DailyAttendanceListResponse {
  total: number
  summary: Record<string, number>
  attendance: DailyAttendanceOut[]
}

export interface AttendanceCorrectRequest {
  status?: AttendanceStatus | null
  first_in?: string | null
  last_out?: string | null
  late_minutes?: number | null
  early_leave_minutes?: number | null
  overtime_minutes?: number | null
  note?: string | null
}

export interface RecomputeResponse {
  work_date: string
  employees: number
  processed: number
  created: number
  updated: number
  skipped_manual: number
}

// --- Data master ----------------------------------------------------------

export type WorkDay = 'MO' | 'TU' | 'WE' | 'TH' | 'FR' | 'SA' | 'SU'

export interface EmployeeOut {
  id: number
  pin: string
  name: string
  employee_code: string | null
  department: string | null
  position: string | null
  email: string | null
  phone: string | null
  joined_at: string | null
  resigned_at: string | null
  is_active: boolean
}

export interface EmployeeListResponse {
  total: number
  employees: EmployeeOut[]
}

export interface EmployeeCreateRequest {
  pin: string
  name: string
  employee_code?: string | null
  department?: string | null
  position?: string | null
  email?: string | null
  phone?: string | null
  joined_at?: string | null
  is_active?: boolean
}

export type EmployeeUpdateRequest = Partial<EmployeeCreateRequest> & {
  resigned_at?: string | null
}

/** Balasan `PATCH /employees/{id}` — bukan `EmployeeOut` biasa. */
export interface EmployeeUpdateResponse {
  employee: EmployeeOut
  unlinked_punches: number
  relinked_punches: number
  message: string
}

export interface ShiftOut {
  id: number
  name: string
  start_time: string
  end_time: string
  late_tolerance_min: number
  early_leave_tol_min: number
  is_overnight: boolean
  is_active: boolean
}

export interface ShiftListResponse {
  total: number
  shifts: ShiftOut[]
}

export interface ShiftCreateRequest {
  name: string
  start_time: string
  end_time: string
  late_tolerance_min?: number
  early_leave_tol_min?: number
  is_overnight?: boolean
  is_active?: boolean
}

export type ShiftUpdateRequest = Partial<ShiftCreateRequest>

export interface ShiftAssignmentOut {
  id: number
  employee_id: number
  pin: string | null
  employee_name: string | null
  shift_id: number
  shift_name: string | null
  effective_from: string
  effective_to: string | null
  work_days: WorkDay[]
}

export interface ShiftAssignmentListResponse {
  total: number
  assignments: ShiftAssignmentOut[]
}

export interface ShiftAssignmentCreateRequest {
  employee_id: number
  shift_id: number
  effective_from: string
  effective_to?: string | null
  work_days?: WorkDay[]
}

export interface HolidayOut {
  id: number
  holiday_date: string
  name: string
  is_recurring: boolean
}

export interface HolidayListResponse {
  total: number
  holidays: HolidayOut[]
}

export interface HolidayCreateRequest {
  holiday_date: string
  name: string
  is_recurring?: boolean
}

// --- Ringkasan dashboard --------------------------------------------------

/**
 * `GET /api/admin/dashboard` menggabungkan tiga ringkasan dalam satu objek
 * (kunci berbeda, nilainya `int`), jadi tipenya adalah gabungan longgar —
 * bukan `Record<string, number>` yang membuat setiap pembacaan kunci jadi
 * tidak aman.
 */
export interface DashboardSummary {
  [key: string]: number | undefined
}

export interface ListParams {
  limit?: number
  offset?: number
  [key: string]: string | number | boolean | undefined
}
