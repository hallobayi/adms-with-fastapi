/**
 * Rekap kehadiran.
 *
 * Dua operasi tulis di sini punya arti yang sangat berbeda dan karena itu
 * dipisah tegas di antarmuka:
 *
 * - **Koreksi manual** — mengubah satu baris dan menandainya `is_manual = 1`.
 *   Baris bertanda itu tidak akan ditimpa olah-ulang berikutnya.
 * - **Olah ulang** — menghitung kembali dari punch mentah, dan **melewati**
 *   baris manual. Hasilnya selalu melaporkan berapa yang dilewati, supaya
 *   admin tidak mengira olah-ulang "tidak bekerja" padahal ia memang menjaga
 *   koreksi manusia.
 *
 * `is_manual` tidak pernah dikirim dari klien — server selalu menyetelnya.
 */

import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { attendanceApi } from '../api/endpoints'
import type { AttendanceStatus, DailyAttendanceOut } from '../api/types'
import { DataTable, type Column } from '../components/DataTable'
import { Checkbox, Field, NumberInput, Select, TextInput } from '../components/Field'
import { Modal } from '../components/Modal'
import { Pagination } from '../components/Pagination'
import { AttendanceStatusBadge, ManualBadge } from '../components/StatusBadge'
import { useToast } from '../components/Toast'
import { QueryState, describeError } from '../components/states'
import { ATTENDANCE_STATUS_OPTIONS, ATTENDANCE_SUMMARY_LABELS } from '../lib/labels'
import { formatDate, formatMinutes, formatTime, orDash, shiftISO, todayISO } from '../lib/format'

const PAGE_SIZE = 50

/** Ringkasan yang ditampilkan sebagai kartu di atas tabel, dalam urutan tetap. */
const SUMMARY_KEYS = [
  'total',
  'present',
  'late',
  'absent',
  'incomplete',
  'holiday',
  'leave',
  'manual',
  'late_minutes_total',
]

export function AttendancePage() {
  const queryClient = useQueryClient()
  const toast = useToast()

  const [mode, setMode] = useState<'day' | 'range'>('day')
  const [workDate, setWorkDate] = useState(todayISO())
  const [dateFrom, setDateFrom] = useState(shiftISO(todayISO(), -6))
  const [dateTo, setDateTo] = useState(todayISO())
  const [employeeId, setEmployeeId] = useState('')
  const [department, setDepartment] = useState('')
  const [status, setStatus] = useState('')
  const [onlyManual, setOnlyManual] = useState(false)
  const [offset, setOffset] = useState(0)

  const [correcting, setCorrecting] = useState<DailyAttendanceOut | null>(null)
  const [recomputing, setRecomputing] = useState(false)

  const params = useMemo(
    () => ({
      work_date: mode === 'day' ? workDate : undefined,
      date_from: mode === 'range' ? dateFrom : undefined,
      date_to: mode === 'range' ? dateTo : undefined,
      employee_id: employeeId.trim() ? Number(employeeId.trim()) : undefined,
      department: department.trim() || undefined,
      status: status ? (status as AttendanceStatus) : undefined,
      only_manual: onlyManual ? true : undefined,
      limit: PAGE_SIZE,
      offset,
    }),
    [mode, workDate, dateFrom, dateTo, employeeId, department, status, onlyManual, offset],
  )

  const query = useQuery({
    queryKey: ['attendance', params],
    queryFn: () => attendanceApi.list(params),
  })

  /** Setiap perubahan filter mengembalikan daftar ke halaman pertama. */
  function update(setter: (value: string) => void) {
    return (value: string) => {
      setter(value)
      setOffset(0)
    }
  }

  const remove = useMutation({
    mutationFn: (attendanceId: number) => attendanceApi.remove(attendanceId),
    onSuccess: (result) => {
      toast.success(result.message)
      void queryClient.invalidateQueries({ queryKey: ['attendance'] })
    },
    onError: (error) => toast.error(describeError(error)),
  })

  const columns: Column<DailyAttendanceOut>[] = [
    {
      key: 'employee',
      header: 'Karyawan',
      render: (row) => (
        <>
          <div>{orDash(row.employee_name)}</div>
          <div className="muted mono" style={{ fontSize: 11.5 }}>PIN {orDash(row.pin)}</div>
        </>
      ),
    },
    {
      key: 'work_date',
      header: 'Tanggal kerja',
      render: (row) => formatDate(row.work_date),
    },
    {
      key: 'shift',
      header: 'Shift',
      render: (row) => orDash(row.shift_name),
    },
    {
      key: 'times',
      header: 'Masuk / keluar',
      render: (row) => (
        <>
          <div>{formatTime(row.first_in)} → {formatTime(row.last_out)}</div>
          <div className="muted" style={{ fontSize: 11.5 }}>{row.punch_count} punch</div>
        </>
      ),
    },
    {
      key: 'late',
      header: 'Terlambat',
      align: 'right',
      render: (row) =>
        row.late_minutes > 0 ? (
          <span className="badge badge--warn">{formatMinutes(row.late_minutes)}</span>
        ) : (
          <span className="faint">—</span>
        ),
    },
    {
      key: 'early',
      header: 'Pulang awal',
      align: 'right',
      render: (row) =>
        row.early_leave_minutes > 0 ? (
          <span className="badge badge--warn">{formatMinutes(row.early_leave_minutes)}</span>
        ) : (
          <span className="faint">—</span>
        ),
    },
    {
      key: 'overtime',
      header: 'Lembur',
      align: 'right',
      render: (row) =>
        row.overtime_minutes > 0 ? (
          <span className="badge badge--info">{formatMinutes(row.overtime_minutes)}</span>
        ) : (
          <span className="faint">—</span>
        ),
    },
    {
      key: 'worked',
      header: 'Jam kerja',
      align: 'right',
      render: (row) => formatMinutes(row.worked_minutes),
    },
    {
      key: 'status',
      header: 'Status',
      render: (row) => (
        <div className="row" style={{ gap: 5, flexWrap: 'nowrap' }}>
          <AttendanceStatusBadge status={row.status} />
          {row.is_manual && <ManualBadge />}
        </div>
      ),
    },
    {
      key: 'note',
      header: 'Catatan',
      render: (row) => (
        <span className="muted" style={{ fontSize: 12.5 }}>{orDash(row.note)}</span>
      ),
    },
  ]

  return (
    <div className="stack">
      <div className="row row--between">
        <div>
          <h1>Kehadiran</h1>
          <div className="muted" style={{ fontSize: 12.5 }}>
            Ringkasan dihitung atas seluruh hasil filter, bukan hanya halaman ini.
          </div>
        </div>
        <button type="button" className="btn btn--sm" onClick={() => setRecomputing(true)}>
          Olah ulang…
        </button>
      </div>

      <div className="card">
        <div className="card__body">
          <div className="row" style={{ marginBottom: 14 }}>
            <button
              type="button"
              className={mode === 'day' ? 'btn btn--primary btn--sm' : 'btn btn--sm'}
              onClick={() => {
                setMode('day')
                setOffset(0)
              }}
            >
              Satu tanggal
            </button>
            <button
              type="button"
              className={mode === 'range' ? 'btn btn--primary btn--sm' : 'btn btn--sm'}
              onClick={() => {
                setMode('range')
                setOffset(0)
              }}
            >
              Rentang tanggal
            </button>
          </div>

          <div className="filters">
            {mode === 'day' ? (
              <Field label="Tanggal kerja">
                <TextInput type="date" value={workDate} onChange={update(setWorkDate)} />
              </Field>
            ) : (
              <>
                <Field label="Dari">
                  <TextInput type="date" value={dateFrom} onChange={update(setDateFrom)} />
                </Field>
                <Field label="Sampai">
                  <TextInput type="date" value={dateTo} onChange={update(setDateTo)} />
                </Field>
              </>
            )}
            <Field label="ID karyawan" hint="Angka; kosongkan untuk semua.">
              <NumberInput value={employeeId} onChange={update(setEmployeeId)} min={1} />
            </Field>
            <Field label="Departemen">
              <TextInput value={department} onChange={update(setDepartment)} />
            </Field>
            <Field label="Status">
              <Select
                value={status}
                onChange={update(setStatus)}
                options={ATTENDANCE_STATUS_OPTIONS}
                placeholder="Semua status"
              />
            </Field>
            <Field label="&nbsp;">
              <Checkbox
                checked={onlyManual}
                onChange={(checked) => {
                  setOnlyManual(checked)
                  setOffset(0)
                }}
                label="Hanya yang dikoreksi manual"
              />
            </Field>
          </div>
        </div>
      </div>

      <QueryState
        isPending={query.isPending}
        error={query.error}
        loadingLabel="Memuat rekap kehadiran…"
        onRetry={() => void query.refetch()}
      >
        {query.data && (
          <>
            <div className="grid grid--stats">
              {SUMMARY_KEYS.filter((key) => query.data.summary[key] !== undefined).map((key) => {
                const value = query.data.summary[key]
                return (
                  <div key={key} className="stat">
                    <div className="stat__label">{ATTENDANCE_SUMMARY_LABELS[key] ?? key}</div>
                    <div className="stat__value">
                      {key === 'late_minutes_total' ? formatMinutes(value) : value}
                    </div>
                  </div>
                )
              })}
            </div>

            <div className="card">
              <QueryState
                isPending={false}
                error={null}
                isEmpty={query.data.attendance.length === 0}
                emptyTitle="Tidak ada baris rekap"
                emptyHint="Coba ubah tanggal, atau jalankan olah ulang bila punch device sudah masuk."
              >
                <DataTable
                  rows={query.data.attendance}
                  columns={columns}
                  rowKey={(row) => row.id}
                  actions={(row) => (
                    <div className="row" style={{ justifyContent: 'flex-end', flexWrap: 'nowrap' }}>
                      <button
                        type="button"
                        className="btn btn--sm"
                        onClick={() => setCorrecting(row)}
                      >
                        Koreksi
                      </button>
                      <button
                        type="button"
                        className="btn btn--danger btn--sm"
                        disabled={remove.isPending}
                        onClick={() => {
                          if (
                            window.confirm(
                              `Hapus baris rekap ${row.employee_name ?? row.pin} pada ${formatDate(row.work_date)}?\n\n` +
                                'Punch mentah di attendance_log tidak ikut terhapus — olah ulang akan membentuknya kembali.',
                            )
                          ) {
                            remove.mutate(row.id)
                          }
                        }}
                      >
                        Hapus
                      </button>
                    </div>
                  )}
                />
                <Pagination
                  total={query.data.total}
                  limit={PAGE_SIZE}
                  offset={offset}
                  onChange={setOffset}
                  disabled={query.isFetching}
                />
              </QueryState>
            </div>
          </>
        )}
      </QueryState>

      {correcting && (
        <CorrectModal
          row={correcting}
          onClose={() => setCorrecting(null)}
          onSaved={(message) => {
            toast.success(message)
            setCorrecting(null)
            void queryClient.invalidateQueries({ queryKey: ['attendance'] })
          }}
        />
      )}

      {recomputing && (
        <RecomputeModal
          defaultDate={mode === 'day' ? workDate : dateFrom}
          onClose={() => setRecomputing(false)}
          onDone={() => {
            void queryClient.invalidateQueries({ queryKey: ['attendance'] })
            void queryClient.invalidateQueries({ queryKey: ['dashboard'] })
          }}
        />
      )}
    </div>
  )
}

// --- Koreksi manual -------------------------------------------------------

interface CorrectModalProps {
  row: DailyAttendanceOut
  onClose: () => void
  onSaved: (message: string) => void
}

/** Ambil bagian jam-menit dari stempel waktu server untuk `<input type="time">`. */
function toTimeInput(value: string | null): string {
  if (!value) return ''
  const [, time = ''] = value.trim().split(/[T ]/)
  return time.slice(0, 5)
}

function CorrectModal({ row, onClose, onSaved }: CorrectModalProps) {
  const toast = useToast()
  const [status, setStatus] = useState<string>(row.status)
  const [firstIn, setFirstIn] = useState(toTimeInput(row.first_in))
  const [lastOut, setLastOut] = useState(toTimeInput(row.last_out))
  const [lateMinutes, setLateMinutes] = useState(String(row.late_minutes))
  const [earlyLeave, setEarlyLeave] = useState(String(row.early_leave_minutes))
  const [overtime, setOvertime] = useState(String(row.overtime_minutes))
  const [note, setNote] = useState(row.note ?? '')

  const save = useMutation({
    mutationFn: () =>
      attendanceApi.correct(row.id, {
        status: status as AttendanceStatus,
        // `null` pada jam berarti "kosongkan", bukan "jangan ubah".
        first_in: firstIn ? `${row.work_date} ${firstIn}:00` : null,
        last_out: lastOut ? `${row.work_date} ${lastOut}:00` : null,
        late_minutes: toNumberOrNull(lateMinutes),
        early_leave_minutes: toNumberOrNull(earlyLeave),
        overtime_minutes: toNumberOrNull(overtime),
        note: note.trim() || null,
      }),
    onSuccess: (result) => onSaved(result.message),
    onError: (error) => toast.error(describeError(error)),
  })

  return (
    <Modal
      title={`Koreksi — ${row.employee_name ?? row.pin} (${formatDate(row.work_date)})`}
      onClose={onClose}
      busy={save.isPending}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose} disabled={save.isPending}>
            Batal
          </button>
          <button
            type="button"
            className="btn btn--primary"
            onClick={() => save.mutate()}
            disabled={save.isPending}
          >
            {save.isPending ? 'Menyimpan…' : 'Simpan koreksi'}
          </button>
        </>
      }
    >
      <div className="stack">
        <div className="login__error" style={{ background: 'var(--warning-soft)', color: 'var(--warning)' }}>
          Baris ini akan ditandai <strong>manual</strong>. Olah ulang berikutnya akan
          melewatinya, sehingga koreksi Anda tidak hilang sendiri.
        </div>

        <Field label="Status">
          <Select
            value={status}
            onChange={setStatus}
            options={ATTENDANCE_STATUS_OPTIONS}
          />
        </Field>

        <div className="grid grid--2">
          <Field label="Jam masuk" hint="Jam dinding lokal, bukan UTC.">
            <TextInput type="time" value={firstIn} onChange={setFirstIn} />
          </Field>
          <Field label="Jam keluar">
            <TextInput type="time" value={lastOut} onChange={setLastOut} />
          </Field>
        </div>

        <div className="grid grid--2">
          <Field label="Terlambat (menit)">
            <NumberInput value={lateMinutes} onChange={setLateMinutes} min={0} />
          </Field>
          <Field label="Pulang awal (menit)">
            <NumberInput value={earlyLeave} onChange={setEarlyLeave} min={0} />
          </Field>
        </div>

        <Field label="Lembur (menit)">
          <NumberInput value={overtime} onChange={setOvertime} min={0} />
        </Field>

        <Field label="Catatan" hint="Alasan koreksi — berguna saat rekap ini dipertanyakan.">
          <TextInput value={note} onChange={setNote} maxLength={255} />
        </Field>
      </div>
    </Modal>
  )
}

/** String kosong berarti "tidak diisi" → `null`, bukan 0. */
function toNumberOrNull(value: string): number | null {
  const trimmed = value.trim()
  if (!trimmed) return null
  const parsed = Number(trimmed)
  return Number.isFinite(parsed) ? parsed : null
}

// --- Olah ulang -----------------------------------------------------------

interface RecomputeModalProps {
  defaultDate: string
  onClose: () => void
  onDone: () => void
}

function RecomputeModal({ defaultDate, onClose, onDone }: RecomputeModalProps) {
  const toast = useToast()
  const [workDate, setWorkDate] = useState(defaultDate)
  const [employeeId, setEmployeeId] = useState('')
  const [overwriteManual, setOverwriteManual] = useState(false)
  const [result, setResult] = useState<string | null>(null)

  const run = useMutation({
    mutationFn: () =>
      attendanceApi.recompute(
        workDate,
        employeeId.trim() ? Number(employeeId.trim()) : undefined,
        overwriteManual,
      ),
    onSuccess: (data) => {
      const summary =
        `${data.created} baris dibuat, ${data.updated} diperbarui, ` +
        `${data.skipped_manual} koreksi manual dilewati (dari ${data.processed} karyawan).`
      setResult(summary)
      toast.success(`Olah ulang ${data.work_date} selesai.`)
      onDone()
    },
    onError: (error) => toast.error(describeError(error)),
  })

  return (
    <Modal
      title="Olah ulang rekap dari punch mentah"
      onClose={onClose}
      busy={run.isPending}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose} disabled={run.isPending}>
            Tutup
          </button>
          <button
            type="button"
            className="btn btn--primary"
            onClick={() => run.mutate()}
            disabled={run.isPending || !workDate}
          >
            {run.isPending ? 'Menghitung…' : 'Jalankan'}
          </button>
        </>
      }
    >
      <div className="stack">
        <Field label="Tanggal kerja" required hint="Punch dikelompokkan memakai tanggal lokal device.">
          <TextInput type="date" value={workDate} onChange={setWorkDate} />
        </Field>

        <Field label="ID karyawan" hint="Kosongkan untuk seluruh karyawan pada tanggal itu.">
          <NumberInput value={employeeId} onChange={setEmployeeId} min={1} />
        </Field>

        <Checkbox
          checked={overwriteManual}
          onChange={setOverwriteManual}
          label="Timpa koreksi manual (overwrite_manual)"
        />
        {overwriteManual && (
          <div className="login__error">
            Peringatan: koreksi manual pada tanggal ini akan <strong>hilang</strong> dan diganti
            hasil hitungan otomatis. Pakai hanya bila data punch-nya sendiri sudah diperbaiki.
          </div>
        )}

        {result && (
          <div className="login__error" style={{ background: 'var(--success-soft)', color: 'var(--success)' }}>
            {result}
          </div>
        )}
      </div>
    </Modal>
  )
}
