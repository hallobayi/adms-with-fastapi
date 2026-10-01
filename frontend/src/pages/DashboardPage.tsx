/**
 * Dashboard: satu panggilan ringkasan, tiga kelompok angka.
 *
 * Angka-angka dikelompokkan dan diberi label eksplisit, bukan diulang apa
 * adanya dari kunci JSON. Alasannya: `unresolved` dan `devices_pending`
 * sama-sama berarti "menunggu tindakan Anda", dan itu harus terbaca dari
 * layar tanpa admin harus tahu nama kolom di database.
 */

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import { dashboardApi } from '../api/endpoints'
import { QueryState } from '../components/states'
import { formatMinutes } from '../lib/format'

interface StatSpec {
  key: string
  label: string
  tone?: 'ok' | 'warn' | 'danger'
  /** Tautan tujuan bila angka ini perlu ditindaklanjuti. */
  to?: string
  /** Tampilkan sebagai durasi, bukan jumlah. */
  duration?: boolean
}

interface StatGroup {
  title: string
  hint?: string
  stats: StatSpec[]
}

const GROUPS: StatGroup[] = [
  {
    title: 'Device',
    hint: 'Kondisi terminal yang mengirim data ke server.',
    stats: [
      { key: 'devices_total', label: 'Total device', to: '/devices' },
      { key: 'devices_active', label: 'Aktif', tone: 'ok' },
      { key: 'devices_pending', label: 'Menunggu persetujuan', tone: 'warn', to: '/devices' },
      { key: 'devices_suspended', label: 'Ditangguhkan', tone: 'danger' },
      { key: 'devices_never_seen', label: 'Belum pernah terhubung', tone: 'warn' },
    ],
  },
  {
    title: 'Arsip request (24 jam terakhir)',
    hint: 'Permintaan mentah yang dikirim device.',
    stats: [
      { key: 'requests_failed_24h', label: 'Gagal diproses', tone: 'danger', to: '/requests' },
      { key: 'requests_stuck_24h', label: 'Tertahan di "diterima"', tone: 'warn', to: '/requests' },
      { key: 'requests_with_duplicates_24h', label: 'Mengandung duplikat', tone: 'warn' },
    ],
  },
  {
    title: 'Konflik sinkronisasi',
    hint: 'Setiap konflik diputuskan manual, satu per satu.',
    stats: [
      { key: 'unresolved', label: 'Belum ditinjau', tone: 'warn', to: '/conflicts' },
      { key: 'resolved', label: 'Sudah diputuskan', tone: 'ok' },
    ],
  },
  {
    title: 'Kehadiran',
    hint: 'Rekap pada jendela hari yang dipilih.',
    stats: [
      { key: 'total', label: 'Baris rekap', to: '/attendance' },
      { key: 'present', label: 'Hadir', tone: 'ok' },
      { key: 'late', label: 'Terlambat', tone: 'warn' },
      { key: 'absent', label: 'Tidak hadir', tone: 'danger' },
      { key: 'incomplete', label: 'Tidak lengkap' },
      { key: 'holiday', label: 'Hari libur' },
      { key: 'leave', label: 'Cuti' },
      { key: 'manual', label: 'Dikoreksi manual' },
      { key: 'late_minutes_total', label: 'Total menit terlambat', duration: true },
    ],
  },
]

const DAY_OPTIONS = [
  { value: 1, label: 'Hari ini' },
  { value: 7, label: '7 hari terakhir' },
  { value: 30, label: '30 hari terakhir' },
]

export function DashboardPage() {
  const [days, setDays] = useState(1)

  const query = useQuery({
    queryKey: ['dashboard', 'summary', days],
    queryFn: () => dashboardApi.summary(days),
    staleTime: 30_000,
  })

  return (
    <div className="stack">
      <div className="row row--between">
        <div>
          <h1>Ringkasan</h1>
          <div className="muted" style={{ fontSize: 12.5 }}>
            Diperbarui otomatis setiap 30 detik.
          </div>
        </div>
        <div className="row">
          {DAY_OPTIONS.map((option) => (
            <button
              key={option.value}
              type="button"
              className={days === option.value ? 'btn btn--primary btn--sm' : 'btn btn--sm'}
              onClick={() => setDays(option.value)}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>

      <QueryState
        isPending={query.isPending}
        error={query.error}
        loadingLabel="Menghitung ringkasan…"
        onRetry={() => void query.refetch()}
      >
        {GROUPS.map((group) => {
          const available = group.stats.filter((stat) => query.data?.[stat.key] !== undefined)
          if (available.length === 0) return null
          return (
            <section key={group.title} className="card">
              <div className="card__header">
                <div>
                  <h2>{group.title}</h2>
                  {group.hint && (
                    <div className="muted" style={{ fontSize: 12 }}>
                      {group.hint}
                    </div>
                  )}
                </div>
              </div>
              <div className="card__body">
                <div className="grid grid--stats">
                  {available.map((stat) => {
                    const raw = query.data?.[stat.key] ?? 0
                    const tone = stat.tone ? ` stat--${stat.tone}` : ''
                    const value = stat.duration ? formatMinutes(raw) : raw
                    const body = (
                      <>
                        <div className="stat__label">{stat.label}</div>
                        <div className="stat__value">{value}</div>
                      </>
                    )
                    return stat.to ? (
                      <Link
                        key={stat.key}
                        to={stat.to}
                        className={`stat${tone}`}
                        style={{ color: 'inherit', textDecoration: 'none' }}
                      >
                        {body}
                      </Link>
                    ) : (
                      <div key={stat.key} className={`stat${tone}`}>
                        {body}
                      </div>
                    )
                  })}
                </div>
              </div>
            </section>
          )
        })}
      </QueryState>
    </div>
  )
}
