/**
 * Label bahasa Indonesia untuk nilai yang dikirim server.
 *
 * Nilai di API sengaja tetap dalam bahasa Inggris (`pending`, `late`,
 * `server_wins`) karena itu yang tersimpan di database. Terjemahannya
 * dikumpulkan di satu berkas supaya tidak ada dua layar yang menyebut status
 * yang sama dengan istilah berbeda — dan supaya penambahan status baru di
 * server cukup diikuti di satu tempat.
 */

import type { AttendanceStatus, DeviceStatus, WorkDay } from '../api/types'

export interface Option<T extends string = string> {
  value: T
  label: string
}

// --- Device ---------------------------------------------------------------

export const DEVICE_STATUS_LABELS: Record<DeviceStatus, string> = {
  pending: 'Menunggu persetujuan',
  active: 'Aktif',
  suspended: 'Ditangguhkan',
}

export const DEVICE_STATUS_OPTIONS: Option<DeviceStatus>[] = [
  { value: 'pending', label: DEVICE_STATUS_LABELS.pending },
  { value: 'active', label: DEVICE_STATUS_LABELS.active },
  { value: 'suspended', label: DEVICE_STATUS_LABELS.suspended },
]

// --- Kehadiran ------------------------------------------------------------

export const ATTENDANCE_STATUS_LABELS: Record<AttendanceStatus, string> = {
  present: 'Hadir',
  late: 'Terlambat',
  absent: 'Tidak hadir',
  incomplete: 'Tidak lengkap',
  holiday: 'Hari libur',
  leave: 'Cuti',
}

export const ATTENDANCE_STATUS_OPTIONS: Option<AttendanceStatus>[] = [
  { value: 'present', label: ATTENDANCE_STATUS_LABELS.present },
  { value: 'late', label: ATTENDANCE_STATUS_LABELS.late },
  { value: 'absent', label: ATTENDANCE_STATUS_LABELS.absent },
  { value: 'incomplete', label: ATTENDANCE_STATUS_LABELS.incomplete },
  { value: 'holiday', label: ATTENDANCE_STATUS_LABELS.holiday },
  { value: 'leave', label: ATTENDANCE_STATUS_LABELS.leave },
]

/**
 * Label kartu ringkasan kehadiran.
 *
 * Kuncinya adalah nama kolom di `queries_attendance.attendance_summary`, jadi
 * daftarnya ditulis manual. Menurunkannya dari kunci (`late` → "Late") akan
 * menghasilkan istilah Inggris — satu-satunya di antarmuka ini. Kunci yang tidak
 * ada di sini tidak ditampilkan sama sekali, sehingga penambahan kunci baru di
 * server tidak pernah menghasilkan label aneh.
 */
export const ATTENDANCE_SUMMARY_LABELS: Record<string, string> = {
  total: 'Baris rekap',
  present: ATTENDANCE_STATUS_LABELS.present,
  late: ATTENDANCE_STATUS_LABELS.late,
  absent: ATTENDANCE_STATUS_LABELS.absent,
  incomplete: ATTENDANCE_STATUS_LABELS.incomplete,
  holiday: ATTENDANCE_STATUS_LABELS.holiday,
  leave: ATTENDANCE_STATUS_LABELS.leave,
  manual: 'Dikoreksi manual',
  late_minutes_total: 'Total menit terlambat',
}

// --- Konflik --------------------------------------------------------------

export const CONFLICT_RESOLUTION_LABELS: Record<string, string> = {
  server_wins: 'Pakai versi server',
  device_wins: 'Pakai versi device',
}

export const CONFLICT_RESOLUTION_OPTIONS: Option[] = [
  { value: 'server_wins', label: CONFLICT_RESOLUTION_LABELS.server_wins },
  { value: 'device_wins', label: CONFLICT_RESOLUTION_LABELS.device_wins },
]

/** Nilai `entity_type` yang dikenal; sisanya ditampilkan apa adanya. */
export const CONFLICT_ENTITY_LABELS: Record<string, string> = {
  user: 'Karyawan',
  userinfo: 'Karyawan',
  fingerprint: 'Sidik jari',
  face: 'Wajah',
  attlog: 'Catatan kehadiran',
}

// --- Hari kerja -----------------------------------------------------------

export const WORK_DAY_LABELS: Record<WorkDay, string> = {
  MO: 'Sen',
  TU: 'Sel',
  WE: 'Rab',
  TH: 'Kam',
  FR: 'Jum',
  SA: 'Sab',
  SU: 'Min',
}

export const WORK_DAY_OPTIONS: Option<WorkDay>[] = (
  ['MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU'] as WorkDay[]
).map((value) => ({ value, label: WORK_DAY_LABELS[value] }))

/** `["MO","TU"]` → `"Sen, Sel"`. */
export function describeWorkDays(days: string[] | null | undefined): string {
  if (!days || days.length === 0) return '—'
  const ordered = (['MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU'] as WorkDay[]).filter((d) =>
    days.includes(d),
  )
  const list = ordered.length ? ordered : (days as WorkDay[])
  return list.map((day) => WORK_DAY_LABELS[day] ?? day).join(', ')
}
