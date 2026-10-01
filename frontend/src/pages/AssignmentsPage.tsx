/**
 * Penugasan shift.
 *
 * Menjawab "siapa masuk shift apa, berlaku sejak kapan". Pasangan
 * (`employee_id`, `effective_from`, `shift_id`) dijaga unik di level database,
 * jadi penugasan ganda pada tanggal mulai yang sama akan ditolak 409 — bukan
 * hanya dicegah oleh validasi formulir. Pesan galatnya ditampilkan apa adanya
 * supaya admin tahu itu aturan database, bukan bug antarmuka.
 *
 * Kolom `work_days` menentukan hari mana yang dianggap hari kerja; di luar itu
 * karyawan tidak dihitung terlambat maupun tidak hadir.
 */

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { assignmentsApi, employeesApi, shiftsApi } from '../api/endpoints'
import type { ShiftAssignmentOut, WorkDay } from '../api/types'
import { DataTable, type Column } from '../components/DataTable'
import { Checkbox, Field, Select, TextInput } from '../components/Field'
import { Modal } from '../components/Modal'
import { Pagination } from '../components/Pagination'
import { Badge } from '../components/StatusBadge'
import { useToast } from '../components/Toast'
import { QueryState, describeError } from '../components/states'
import { WORK_DAY_OPTIONS, describeWorkDays } from '../lib/labels'
import { formatDate, orDash, todayISO } from '../lib/format'

const PAGE_SIZE = 50
const DEFAULT_WORK_DAYS: WorkDay[] = ['MO', 'TU', 'WE', 'TH', 'FR']

export function AssignmentsPage() {
  const queryClient = useQueryClient()
  const toast = useToast()

  const [employeeId, setEmployeeId] = useState('')
  const [shiftId, setShiftId] = useState('')
  const [activeOn, setActiveOn] = useState('')
  const [offset, setOffset] = useState(0)
  const [creating, setCreating] = useState(false)

  // Daftar karyawan dan shift dipakai untuk mengisi pemilih, sekaligus supaya
  // formulir tidak meminta admin menghafal id numerik.
  const employeesQuery = useQuery({
    queryKey: ['employees', 'options'],
    queryFn: () => employeesApi.list({ is_active: true, limit: 500 }),
    staleTime: 5 * 60_000,
  })

  const shiftsQuery = useQuery({
    queryKey: ['shifts', 'options'],
    queryFn: () => shiftsApi.list(true),
    staleTime: 5 * 60_000,
  })

  const query = useQuery({
    queryKey: ['assignments', { employeeId, shiftId, activeOn, offset }],
    queryFn: () =>
      assignmentsApi.list({
        employee_id: employeeId ? Number(employeeId) : undefined,
        shift_id: shiftId ? Number(shiftId) : undefined,
        active_on: activeOn || undefined,
        limit: PAGE_SIZE,
        offset,
      }),
  })

  const remove = useMutation({
    mutationFn: (assignmentId: number) => assignmentsApi.remove(assignmentId),
    onSuccess: (result) => {
      toast.success(result.message)
      void queryClient.invalidateQueries({ queryKey: ['assignments'] })
    },
    onError: (error) => toast.error(describeError(error)),
  })

  const columns: Column<ShiftAssignmentOut>[] = [
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
      key: 'shift',
      header: 'Shift',
      render: (row) => orDash(row.shift_name),
    },
    {
      key: 'period',
      header: 'Berlaku',
      render: (row) => (
        <>
          <div>{formatDate(row.effective_from)}</div>
          <div className="muted" style={{ fontSize: 11.5 }}>
            {row.effective_to ? `sampai ${formatDate(row.effective_to)}` : 'tanpa batas'}
          </div>
        </>
      ),
    },
    {
      key: 'work_days',
      header: 'Hari kerja',
      render: (row) => describeWorkDays(row.work_days),
    },
  ]

  return (
    <div className="stack">
      <div className="row row--between">
        <div>
          <h1>Penugasan shift</h1>
          <div className="muted" style={{ fontSize: 12.5 }}>
            Kombinasi karyawan, shift, dan tanggal mulai dijaga unik oleh database.
          </div>
        </div>
        <button type="button" className="btn btn--primary btn--sm" onClick={() => setCreating(true)}>
          Tugaskan shift
        </button>
      </div>

      <div className="card">
        <div className="card__body">
          <div className="filters">
            <Field label="Karyawan">
              <Select
                value={employeeId}
                onChange={(value) => {
                  setEmployeeId(value)
                  setOffset(0)
                }}
                placeholder="Semua karyawan"
                options={(employeesQuery.data?.employees ?? []).map((employee) => ({
                  value: String(employee.id),
                  label: `${employee.name} (${employee.pin})`,
                }))}
              />
            </Field>
            <Field label="Shift">
              <Select
                value={shiftId}
                onChange={(value) => {
                  setShiftId(value)
                  setOffset(0)
                }}
                placeholder="Semua shift"
                options={(shiftsQuery.data?.shifts ?? []).map((shift) => ({
                  value: String(shift.id),
                  label: shift.name,
                }))}
              />
            </Field>
            <Field label="Berlaku pada" hint="Tampilkan penugasan yang aktif pada tanggal ini.">
              <TextInput
                type="date"
                value={activeOn}
                onChange={(value) => {
                  setActiveOn(value)
                  setOffset(0)
                }}
              />
            </Field>
          </div>
        </div>
      </div>

      <div className="card">
        <QueryState
          isPending={query.isPending}
          error={query.error}
          isEmpty={query.data?.assignments.length === 0}
          emptyTitle="Belum ada penugasan"
          emptyHint="Tanpa penugasan, karyawan tidak punya jam kerja pembanding."
          loadingLabel="Memuat penugasan…"
          onRetry={() => void query.refetch()}
        >
          <DataTable
            rows={query.data?.assignments ?? []}
            columns={columns}
            rowKey={(row) => row.id}
            actions={(row) => (
              <button
                type="button"
                className="btn btn--danger btn--sm"
                disabled={remove.isPending}
                onClick={() => {
                  if (
                    window.confirm(
                      `Hapus penugasan ${row.employee_name ?? row.pin} pada shift ${row.shift_name}?`,
                    )
                  ) {
                    remove.mutate(row.id)
                  }
                }}
              >
                Hapus
              </button>
            )}
          />
          <Pagination
            total={query.data?.total ?? 0}
            limit={PAGE_SIZE}
            offset={offset}
            onChange={setOffset}
            disabled={query.isFetching}
          />
        </QueryState>
      </div>

      {creating && (
        <AssignmentFormModal
          employees={(employeesQuery.data?.employees ?? []).map((e) => ({
            id: e.id,
            label: `${e.name} (${e.pin})`,
          }))}
          shifts={(shiftsQuery.data?.shifts ?? []).map((s) => ({ id: s.id, label: s.name }))}
          onClose={() => setCreating(false)}
          onSaved={(message) => {
            toast.success(message)
            setCreating(false)
            void queryClient.invalidateQueries({ queryKey: ['assignments'] })
          }}
        />
      )}
    </div>
  )
}

// --- Formulir penugasan ---------------------------------------------------

interface Choice {
  id: number
  label: string
}

interface AssignmentFormModalProps {
  employees: Choice[]
  shifts: Choice[]
  onClose: () => void
  onSaved: (message: string) => void
}

function AssignmentFormModal({ employees, shifts, onClose, onSaved }: AssignmentFormModalProps) {
  const toast = useToast()

  const [employeeId, setEmployeeId] = useState(employees[0] ? String(employees[0].id) : '')
  const [shiftId, setShiftId] = useState(shifts[0] ? String(shifts[0].id) : '')
  const [effectiveFrom, setEffectiveFrom] = useState(todayISO())
  const [effectiveTo, setEffectiveTo] = useState('')
  const [workDays, setWorkDays] = useState<WorkDay[]>(DEFAULT_WORK_DAYS)

  const save = useMutation({
    mutationFn: () =>
      assignmentsApi.create({
        employee_id: Number(employeeId),
        shift_id: Number(shiftId),
        effective_from: effectiveFrom,
        effective_to: effectiveTo || null,
        work_days: workDays,
      }),
    onSuccess: (result) => onSaved(result.message),
    onError: (error) => toast.error(describeError(error)),
  })

  function toggleDay(day: WorkDay, checked: boolean) {
    setWorkDays((current) => {
      const next = checked
        ? current.includes(day)
          ? current
          : [...current, day]
        : current.filter((item) => item !== day)
      // Simpan dalam urutan kanonis supaya nilainya stabil saat dibandingkan.
      return WORK_DAY_OPTIONS.map((option) => option.value).filter((value) => next.includes(value))
    })
  }

  const invalidPeriod = Boolean(effectiveTo) && effectiveTo < effectiveFrom
  const noDays = workDays.length === 0

  return (
    <Modal
      title="Tugaskan shift"
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
            disabled={save.isPending || !employeeId || !shiftId || invalidPeriod || noDays}
          >
            {save.isPending ? 'Menyimpan…' : 'Simpan'}
          </button>
        </>
      }
    >
      <div className="stack">
        {employees.length === 0 || shifts.length === 0 ? (
          <div className="login__error">
            Butuh minimal satu karyawan aktif dan satu shift aktif sebelum penugasan bisa dibuat.
          </div>
        ) : null}

        <Field label="Karyawan" required>
          <Select
            value={employeeId}
            onChange={setEmployeeId}
            placeholder="— pilih karyawan —"
            options={employees.map((employee) => ({
              value: String(employee.id),
              label: employee.label,
            }))}
          />
        </Field>

        <Field label="Shift" required>
          <Select
            value={shiftId}
            onChange={setShiftId}
            placeholder="— pilih shift —"
            options={shifts.map((shift) => ({ value: String(shift.id), label: shift.label }))}
          />
        </Field>

        <div className="grid grid--2">
          <Field label="Berlaku sejak" required>
            <TextInput type="date" value={effectiveFrom} onChange={setEffectiveFrom} />
          </Field>
          <Field
            label="Berlaku sampai"
            error={invalidPeriod ? 'Tidak boleh lebih awal dari tanggal mulai.' : null}
            hint="Kosongkan bila penugasan tidak dibatasi waktu."
          >
            <TextInput type="date" value={effectiveTo} onChange={setEffectiveTo} />
          </Field>
        </div>

        <Field label="Hari kerja" error={noDays ? 'Pilih minimal satu hari.' : null} required>
          <div className="row" style={{ gap: 14 }}>
            {WORK_DAY_OPTIONS.map((option) => (
              <Checkbox
                key={option.value}
                checked={workDays.includes(option.value)}
                onChange={(checked) => toggleDay(option.value, checked)}
                label={option.label}
              />
            ))}
          </div>
        </Field>

        <div className="row">
          <button
            type="button"
            className="btn btn--link"
            onClick={() => setWorkDays(DEFAULT_WORK_DAYS)}
          >
            Senin–Jumat
          </button>
          <Badge tone="neutral">Bawaan: {describeWorkDays(DEFAULT_WORK_DAYS)}</Badge>
        </div>
      </div>
    </Modal>
  )
}
