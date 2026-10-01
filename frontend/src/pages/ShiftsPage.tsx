/**
 * Shift kerja.
 *
 * `start_time` dan `end_time` adalah **jam dinding setempat**, bukan UTC —
 * nilai inilah yang dipakai untuk menghitung keterlambatan. Karena itu
 * formulirnya memakai pemilih jam, bukan teks bebas: salah ketik satu digit di
 * sini akan menggeser perhitungan keterlambatan seluruh karyawan yang memakai
 * shift tersebut, tanpa memunculkan error apa pun.
 *
 * `is_overnight` menandai shift yang melewati tengah malam (mis. 22:00 → 06:00);
 * tanpa penanda itu, jam keluar yang lebih kecil dari jam masuk akan terbaca
 * sebagai pulang lebih awal.
 */

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { shiftsApi } from '../api/endpoints'
import type { ShiftOut } from '../api/types'
import { DataTable, type Column } from '../components/DataTable'
import { Checkbox, Field, NumberInput, Select, TextInput } from '../components/Field'
import { Modal } from '../components/Modal'
import { Badge } from '../components/StatusBadge'
import { useToast } from '../components/Toast'
import { QueryState, describeError } from '../components/states'
import { formatMinutes } from '../lib/format'

const ACTIVE_OPTIONS = [
  { value: 'true', label: 'Aktif' },
  { value: 'false', label: 'Tidak aktif' },
]

export function ShiftsPage() {
  const queryClient = useQueryClient()
  const toast = useToast()

  const [isActive, setIsActive] = useState('')
  const [editing, setEditing] = useState<ShiftOut | null>(null)
  const [creating, setCreating] = useState(false)

  const query = useQuery({
    queryKey: ['shifts', { isActive }],
    queryFn: () => shiftsApi.list(isActive ? isActive === 'true' : undefined),
  })

  const remove = useMutation({
    mutationFn: (shiftId: number) => shiftsApi.remove(shiftId),
    onSuccess: (result) => {
      toast.success(result.message)
      void queryClient.invalidateQueries({ queryKey: ['shifts'] })
    },
    onError: (error) => toast.error(describeError(error)),
  })

  function refresh() {
    void queryClient.invalidateQueries({ queryKey: ['shifts'] })
  }

  const columns: Column<ShiftOut>[] = [
    {
      key: 'name',
      header: 'Nama shift',
      render: (row) => row.name,
    },
    {
      key: 'hours',
      header: 'Jam kerja',
      render: (row) => (
        <>
          <div className="mono">{row.start_time.slice(0, 5)} → {row.end_time.slice(0, 5)}</div>
          {row.is_overnight && (
            <div style={{ marginTop: 3 }}>
              <Badge tone="info">Lewat tengah malam</Badge>
            </div>
          )}
        </>
      ),
    },
    {
      key: 'late_tol',
      header: 'Toleransi telat',
      align: 'right',
      render: (row) => formatMinutes(row.late_tolerance_min),
    },
    {
      key: 'early_tol',
      header: 'Toleransi pulang awal',
      align: 'right',
      render: (row) => formatMinutes(row.early_leave_tol_min),
    },
    {
      key: 'active',
      header: 'Status',
      render: (row) =>
        row.is_active ? <Badge tone="ok">Aktif</Badge> : <Badge tone="neutral">Tidak aktif</Badge>,
    },
  ]

  return (
    <div className="stack">
      <div className="row row--between">
        <div>
          <h1>Shift</h1>
          <div className="muted" style={{ fontSize: 12.5 }}>
            Jam dinding setempat. Nilai ini yang dipakai menghitung keterlambatan.
          </div>
        </div>
        <button type="button" className="btn btn--primary btn--sm" onClick={() => setCreating(true)}>
          Tambah shift
        </button>
      </div>

      <div className="card">
        <div className="card__body">
          <div className="filters">
            <Field label="Status">
              <Select
                value={isActive}
                onChange={setIsActive}
                placeholder="Semua"
                options={ACTIVE_OPTIONS}
              />
            </Field>
          </div>
        </div>
      </div>

      <div className="card">
        <QueryState
          isPending={query.isPending}
          error={query.error}
          isEmpty={query.data?.shifts.length === 0}
          emptyTitle="Belum ada shift"
          emptyHint="Shift dibutuhkan sebelum penugasan bisa dibuat."
          loadingLabel="Memuat shift…"
          onRetry={() => void query.refetch()}
        >
          <DataTable
            rows={query.data?.shifts ?? []}
            columns={columns}
            rowKey={(row) => row.id}
            actions={(row) => (
              <div className="row" style={{ justifyContent: 'flex-end', flexWrap: 'nowrap' }}>
                <button type="button" className="btn btn--sm" onClick={() => setEditing(row)}>
                  Ubah
                </button>
                <button
                  type="button"
                  className="btn btn--danger btn--sm"
                  disabled={remove.isPending}
                  onClick={() => {
                    if (window.confirm(`Hapus shift ${row.name}?`)) remove.mutate(row.id)
                  }}
                >
                  Hapus
                </button>
              </div>
            )}
          />
        </QueryState>
      </div>

      {creating && (
        <ShiftFormModal
          onClose={() => setCreating(false)}
          onSaved={(message) => {
            toast.success(message)
            setCreating(false)
            refresh()
          }}
        />
      )}

      {editing && (
        <ShiftFormModal
          shift={editing}
          onClose={() => setEditing(null)}
          onSaved={(message) => {
            toast.success(message)
            setEditing(null)
            refresh()
          }}
        />
      )}
    </div>
  )
}

// --- Formulir tambah / ubah ----------------------------------------------

interface ShiftFormModalProps {
  shift?: ShiftOut
  onClose: () => void
  onSaved: (message: string) => void
}

/** `"08:00:00"` → `"08:00"` untuk `<input type="time">`. */
function toTimeInput(value: string | undefined): string {
  return value ? value.slice(0, 5) : ''
}

function ShiftFormModal({ shift, onClose, onSaved }: ShiftFormModalProps) {
  const toast = useToast()
  const isEdit = shift !== undefined

  const [name, setName] = useState(shift?.name ?? '')
  const [startTime, setStartTime] = useState(toTimeInput(shift?.start_time))
  const [endTime, setEndTime] = useState(toTimeInput(shift?.end_time))
  const [lateTolerance, setLateTolerance] = useState(String(shift?.late_tolerance_min ?? 0))
  const [earlyTolerance, setEarlyTolerance] = useState(String(shift?.early_leave_tol_min ?? 0))
  const [isOvernight, setIsOvernight] = useState(shift?.is_overnight ?? false)
  const [isActive, setIsActive] = useState(shift?.is_active ?? true)

  const save = useMutation({
    mutationFn: async () => {
      const payload = {
        name: name.trim(),
        start_time: startTime,
        end_time: endTime,
        late_tolerance_min: toNumber(lateTolerance),
        early_leave_tol_min: toNumber(earlyTolerance),
        is_overnight: isOvernight,
        is_active: isActive,
      }
      if (!shift) {
        const created = await shiftsApi.create(payload)
        return `Shift ${created.name} dibuat.`
      }
      const updated = await shiftsApi.update(shift.id, payload)
      return `Shift ${updated.name} diperbarui.`
    },
    onSuccess: (message) => onSaved(message),
    onError: (error) => toast.error(describeError(error)),
  })

  return (
    <Modal
      title={isEdit ? `Ubah shift ${shift?.name}` : 'Tambah shift'}
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
            disabled={save.isPending || !name.trim() || !startTime || !endTime}
          >
            {save.isPending ? 'Menyimpan…' : 'Simpan'}
          </button>
        </>
      }
    >
      <div className="stack">
        <Field label="Nama shift" required hint="Harus unik — nama ganda ditolak server.">
          <TextInput value={name} onChange={setName} maxLength={64} />
        </Field>

        <div className="grid grid--2">
          <Field label="Jam masuk" required>
            <TextInput type="time" value={startTime} onChange={setStartTime} />
          </Field>
          <Field label="Jam keluar" required>
            <TextInput type="time" value={endTime} onChange={setEndTime} />
          </Field>
        </div>

        <Checkbox
          checked={isOvernight}
          onChange={setIsOvernight}
          label="Melewati tengah malam (mis. 22:00 → 06:00)"
        />

        <div className="grid grid--2">
          <Field label="Toleransi terlambat (menit)" hint="Maks. 1440.">
            <NumberInput value={lateTolerance} onChange={setLateTolerance} min={0} max={1440} />
          </Field>
          <Field label="Toleransi pulang awal (menit)" hint="Maks. 1440.">
            <NumberInput value={earlyTolerance} onChange={setEarlyTolerance} min={0} max={1440} />
          </Field>
        </div>

        <Checkbox checked={isActive} onChange={setIsActive} label="Shift aktif" />
      </div>
    </Modal>
  )
}

function toNumber(value: string): number {
  const parsed = Number(value.trim())
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : 0
}
