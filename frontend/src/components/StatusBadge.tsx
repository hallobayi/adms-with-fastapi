/**
 * Lencana status.
 *
 * Warna dipilih berdasarkan **tingkat perhatian yang dibutuhkan**, bukan
 * sekadar pemetaan satu-ke-satu: `pending` pada device berarti "menunggu
 * keputusan admin" sehingga berwarna peringatan, sedangkan `received` pada
 * arsip request hanyalah keadaan normal sehingga berwarna netral. Menyamakan
 * keduanya akan membuat layar penuh warna merah tanpa ada yang benar-benar
 * perlu ditindak.
 */

import type { ReactNode } from 'react'

import type { AttendanceStatus, DeviceStatus } from '../api/types'
import {
  ATTENDANCE_STATUS_LABELS,
  DEVICE_STATUS_LABELS,
} from '../lib/labels'

export type Tone = 'neutral' | 'ok' | 'warn' | 'danger' | 'info' | 'primary'

export function Badge({ tone = 'neutral', children }: { tone?: Tone; children: ReactNode }) {
  return <span className={`badge badge--${tone}`}>{children}</span>
}

/** Lencana dengan titik warna — menandai keadaan yang sedang berlangsung. */
export function DotBadge({ tone = 'neutral', children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span className={`badge badge--${tone}`}>
      <span className="dot" />
      {children}
    </span>
  )
}

const DEVICE_TONE: Record<DeviceStatus, Tone> = {
  pending: 'warn',
  active: 'ok',
  suspended: 'danger',
}

export function DeviceStatusBadge({ status }: { status: string }) {
  const key = status as DeviceStatus
  const label = DEVICE_STATUS_LABELS[key] ?? status
  return <DotBadge tone={DEVICE_TONE[key] ?? 'neutral'}>{label}</DotBadge>
}

const ATTENDANCE_TONE: Record<AttendanceStatus, Tone> = {
  present: 'ok',
  late: 'warn',
  absent: 'danger',
  incomplete: 'info',
  holiday: 'info',
  leave: 'info',
}

export function AttendanceStatusBadge({ status }: { status: string }) {
  const key = status as AttendanceStatus
  const label = ATTENDANCE_STATUS_LABELS[key] ?? status
  return <Badge tone={ATTENDANCE_TONE[key] ?? 'neutral'}>{label}</Badge>
}

const PROCESS_TONE: Record<string, Tone> = {
  processed: 'ok',
  received: 'neutral',
  failed: 'danger',
  skipped: 'warn',
}

const PROCESS_LABELS: Record<string, string> = {
  processed: 'Diproses',
  received: 'Diterima',
  failed: 'Gagal',
  skipped: 'Dilewati',
}

export function ProcessStatusBadge({ status }: { status: string }) {
  return (
    <Badge tone={PROCESS_TONE[status] ?? 'neutral'}>{PROCESS_LABELS[status] ?? status}</Badge>
  )
}

/** Lencana kecil untuk menandai baris yang dikoreksi manusia. */
export function ManualBadge() {
  return <Badge tone="primary">Manual</Badge>
}
