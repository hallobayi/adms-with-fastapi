/**
 * Satu kumpulan fungsi per grup endpoint `/api/admin/*`.
 *
 * Modul ini **tidak** menyimpan state dan tidak tahu React — ia hanya
 * menerjemahkan "apa yang ingin dilakukan" menjadi permintaan HTTP. Berkat itu
 * setiap hook TanStack Query cukup memanggil satu fungsi di sini, dan tidak ada
 * URL yang ditulis sebagai string di dalam komponen.
 */

import { apiFetch } from './client'
import type {
  AccountListResponse,
  AdminCreateRequest,
  AdminMe,
  AdminUpdateRequest,
  AttendanceCorrectRequest,
  AttendanceStatus,
  ConflictListResponse,
  ConflictOut,
  ConflictResolution,
  ConflictResolveResponse,
  DailyAttendanceListResponse,
  DashboardSummary,
  DeviceListResponse,
  DeviceOut,
  DeviceStatus,
  DeviceUpdateRequest,
  EmployeeCreateRequest,
  EmployeeListResponse,
  EmployeeOut,
  EmployeeUpdateRequest,
  EmployeeUpdateResponse,
  HolidayCreateRequest,
  HolidayListResponse,
  HolidayOut,
  LoginResponse,
  MessageResponse,
  RecomputeResponse,
  RequestListResponse,
  RequestOut,
  ShiftAssignmentCreateRequest,
  ShiftAssignmentListResponse,
  ShiftCreateRequest,
  ShiftListResponse,
  ShiftOut,
  ShiftUpdateRequest,
  WorkDay,
} from './types'

// --- Auth -----------------------------------------------------------------

export const authApi = {
  login: (username: string, password: string) =>
    apiFetch<LoginResponse>('/auth/login', { method: 'POST', body: { username, password } }),

  logout: () => apiFetch<MessageResponse>('/auth/logout', { method: 'POST' }),

  me: () => apiFetch<AdminMe>('/auth/me'),

  /** Ganti password sendiri; seluruh sesi (termasuk yang ini) dicabut server. */
  changePassword: (currentPassword: string, newPassword: string) =>
    apiFetch<MessageResponse>('/auth/password', {
      method: 'POST',
      body: { current_password: currentPassword, new_password: newPassword },
    }),
}

// --- Ringkasan ------------------------------------------------------------

export const dashboardApi = {
  summary: (days = 1) => apiFetch<DashboardSummary>('/dashboard', { query: { days } }),
}

// --- Device ---------------------------------------------------------------

export interface DeviceListParams {
  status?: DeviceStatus
  search?: string
  limit?: number
  offset?: number
}

export const devicesApi = {
  list: (params: DeviceListParams = {}) =>
    apiFetch<DeviceListResponse>('/devices', { query: { ...params } }),

  /** Ringkasan device + kesehatan request 24 jam terakhir. */
  summary: () => apiFetch<Record<string, number>>('/devices/summary'),

  get: (deviceId: number) => apiFetch<DeviceOut>(`/devices/${deviceId}`),

  update: (deviceId: number, payload: DeviceUpdateRequest) =>
    apiFetch<DeviceOut>(`/devices/${deviceId}`, { method: 'PATCH', body: payload }),

  /** Setujui device `pending` supaya datanya dipercaya. */
  approve: (deviceId: number) =>
    apiFetch<MessageResponse>(`/devices/${deviceId}/approve`, { method: 'POST' }),
}

// --- Arsip request --------------------------------------------------------

export interface RequestListParams {
  serial_number?: string
  table_name?: string
  process_status?: string
  since?: string
  limit?: number
  offset?: number
}

export const requestsApi = {
  list: (params: RequestListParams = {}) =>
    apiFetch<RequestListResponse>('/requests', { query: { ...params } }),

  /** Satu request beserta body mentahnya (dipotong server bila terlalu panjang). */
  get: (requestId: number) => apiFetch<RequestOut>(`/requests/${requestId}`),
}

// --- Konflik --------------------------------------------------------------

export interface ConflictListParams {
  serial_number?: string
  entity_type?: string
  /** `false` = antrean belum ditinjau (default server); `true` = sudah; kosong = semua. */
  resolved?: boolean
  limit?: number
  offset?: number
}

export const conflictsApi = {
  list: (params: ConflictListParams = {}) =>
    apiFetch<ConflictListResponse>('/conflicts', { query: { ...params } }),

  summary: () => apiFetch<Record<string, number>>('/conflicts/summary'),

  get: (conflictId: number) => apiFetch<ConflictOut>(`/conflicts/${conflictId}`),

  /**
   * Putuskan satu konflik. Keputusan **selalu** manual dan satu per satu —
   * tidak ada endpoint "selesaikan semua" di sisi server.
   */
  resolve: (conflictId: number, resolution: ConflictResolution, note?: string) =>
    apiFetch<ConflictResolveResponse>(`/conflicts/${conflictId}/resolve`, {
      method: 'POST',
      body: { resolution, note: note?.trim() ? note.trim() : null },
    }),
}

// --- Kehadiran ------------------------------------------------------------

export interface AttendanceListParams {
  work_date?: string
  date_from?: string
  date_to?: string
  employee_id?: number
  department?: string
  status?: AttendanceStatus
  only_manual?: boolean
  limit?: number
  offset?: number
}

export const attendanceApi = {
  list: (params: AttendanceListParams = {}) =>
    apiFetch<DailyAttendanceListResponse>('/attendance', { query: { ...params } }),

  summary: (days = 1) =>
    apiFetch<Record<string, number>>('/attendance/summary', { query: { days } }),

  /** Koreksi manual; server selalu menandai baris `is_manual = 1`. */
  correct: (attendanceId: number, payload: AttendanceCorrectRequest) =>
    apiFetch<MessageResponse>(`/attendance/${attendanceId}`, {
      method: 'PATCH',
      body: payload,
    }),

  remove: (attendanceId: number) =>
    apiFetch<MessageResponse>(`/attendance/${attendanceId}`, { method: 'DELETE' }),

  /**
   * Olah ulang rekap dari punch mentah. Baris yang dikoreksi manual dilewati
   * kecuali `overwrite_manual` diminta eksplisit.
   */
  recompute: (workDate: string, employeeId?: number, overwriteManual = false) =>
    apiFetch<RecomputeResponse>('/attendance/recompute', {
      method: 'POST',
      query: {
        work_date: workDate,
        employee_id: employeeId,
        overwrite_manual: overwriteManual,
      },
    }),
}

// --- Data master: karyawan ------------------------------------------------

export interface EmployeeListParams {
  search?: string
  department?: string
  is_active?: boolean
  limit?: number
  offset?: number
}

export const employeesApi = {
  list: (params: EmployeeListParams = {}) =>
    apiFetch<EmployeeListResponse>('/employees', { query: { ...params } }),

  departments: () =>
    apiFetch<{ departments: string[] }>('/employees/departments').then((r) => r.departments),

  get: (employeeId: number) => apiFetch<EmployeeOut>(`/employees/${employeeId}`),

  create: (payload: EmployeeCreateRequest) =>
    apiFetch<EmployeeOut>('/employees', { method: 'POST', body: payload }),

  /**
   * Perbarui karyawan. Bila PIN berubah, balasan melaporkan berapa punch lama
   * yang tautannya terputus — itu informasi yang harus ditampilkan, bukan
   * disembunyikan.
   */
  update: (employeeId: number, payload: EmployeeUpdateRequest) =>
    apiFetch<EmployeeUpdateResponse>(`/employees/${employeeId}`, {
      method: 'PATCH',
      body: payload,
    }),

  remove: (employeeId: number) =>
    apiFetch<MessageResponse>(`/employees/${employeeId}`, { method: 'DELETE' }),
}

// --- Data master: shift ---------------------------------------------------

export const shiftsApi = {
  list: (isActive?: boolean) =>
    apiFetch<ShiftListResponse>('/shifts', { query: { is_active: isActive } }),

  get: (shiftId: number) => apiFetch<ShiftOut>(`/shifts/${shiftId}`),

  create: (payload: ShiftCreateRequest) =>
    apiFetch<ShiftOut>('/shifts', { method: 'POST', body: payload }),

  update: (shiftId: number, payload: ShiftUpdateRequest) =>
    apiFetch<ShiftOut>(`/shifts/${shiftId}`, { method: 'PATCH', body: payload }),

  /** Ditolak 409 bila shift masih dipakai penugasan. */
  remove: (shiftId: number) =>
    apiFetch<MessageResponse>(`/shifts/${shiftId}`, { method: 'DELETE' }),
}

// --- Data master: penugasan shift -----------------------------------------

export interface AssignmentListParams {
  employee_id?: number
  shift_id?: number
  active_on?: string
  limit?: number
  offset?: number
}

export const assignmentsApi = {
  list: (params: AssignmentListParams = {}) =>
    apiFetch<ShiftAssignmentListResponse>('/shift-assignments', { query: { ...params } }),

  create: (payload: ShiftAssignmentCreateRequest) =>
    apiFetch<MessageResponse>('/shift-assignments', { method: 'POST', body: payload }),

  remove: (assignmentId: number) =>
    apiFetch<MessageResponse>(`/shift-assignments/${assignmentId}`, { method: 'DELETE' }),
}

// --- Data master: hari libur ----------------------------------------------

export interface HolidayListParams {
  year?: number
  limit?: number
  offset?: number
}

export const holidaysApi = {
  list: (params: HolidayListParams = {}) =>
    apiFetch<HolidayListResponse>('/holidays', { query: { ...params } }),

  create: (payload: HolidayCreateRequest) =>
    apiFetch<HolidayOut>('/holidays', { method: 'POST', body: payload }),

  remove: (holidayId: number) =>
    apiFetch<MessageResponse>(`/holidays/${holidayId}`, { method: 'DELETE' }),
}

// --- Akun admin (khusus superuser) ----------------------------------------

export const accountsApi = {
  list: () => apiFetch<AccountListResponse>('/accounts'),

  create: (payload: AdminCreateRequest) =>
    apiFetch<{ id: number; username: string; is_superuser: boolean; message: string }>(
      '/accounts',
      { method: 'POST', body: payload },
    ),

  update: (adminId: number, payload: AdminUpdateRequest) =>
    apiFetch<{ id: number; message: string }>(`/accounts/${adminId}`, {
      method: 'PATCH',
      body: payload,
    }),
}

export type { WorkDay }
