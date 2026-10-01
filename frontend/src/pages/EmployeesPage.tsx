/**
 * Data karyawan.
 *
 * PIN adalah jembatan antara karyawan dan punch di device: `attendance_log.pin`
 * dicocokkan ke `employee.pin`. Karena itu mengubah PIN bukan sekadar mengedit
 * satu kolom — punch lama bisa kehilangan tautannya. Server melaporkan berapa
 * yang terputus dan berapa yang tertaut ulang, dan laporan itu **ditampilkan**,
 * bukan disimpulkan sebagai "berhasil".
 */

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { employeesApi } from '../api/endpoints'
import type { EmployeeOut } from '../api/types'
import { DataTable, type Column } from '../components/DataTable'
import { Checkbox, Field, Select, TextInput } from '../components/Field'
import { Modal } from '../components/Modal'
import { Pagination } from '../components/Pagination'
import { Badge } from '../components/StatusBadge'
import { useToast } from '../components/Toast'
import { QueryState, describeError } from '../components/states'
import { formatDate, orDash } from '../lib/format'

const PAGE_SIZE = 50

const ACTIVE_OPTIONS = [
  { value: 'true', label: 'Aktif' },
  { value: 'false', label: 'Tidak aktif' },
]

export function EmployeesPage() {
  const queryClient = useQueryClient()
  const toast = useToast()

  const [search, setSearch] = useState('')
  const [department, setDepartment] = useState('')
  const [isActive, setIsActive] = useState('')
  const [offset, setOffset] = useState(0)
  const [editing, setEditing] = useState<EmployeeOut | null>(null)
  const [creating, setCreating] = useState(false)

  const departmentsQuery = useQuery({
    queryKey: ['employees', 'departments'],
    queryFn: () => employeesApi.departments(),
    staleTime: 5 * 60_000,
  })

  const query = useQuery({
    queryKey: ['employees', { search, department, isActive, offset }],
    queryFn: () =>
      employeesApi.list({
        search: search.trim() || undefined,
        department: department || undefined,
        is_active: isActive ? isActive === 'true' : undefined,
        limit: PAGE_SIZE,
        offset,
      }),
  })

  const remove = useMutation({
    mutationFn: (employeeId: number) => employeesApi.remove(employeeId),
    onSuccess: (result) => {
      toast.success(`${result.message} Punch-nya tetap tersimpan dengan employee_id kosong.`)
      void queryClient.invalidateQueries({ queryKey: ['employees'] })
    },
    onError: (error) => toast.error(describeError(error)),
  })

  function refresh() {
    void queryClient.invalidateQueries({ queryKey: ['employees'] })
  }

  const columns: Column<EmployeeOut>[] = [
    {
      key: 'pin',
      header: 'PIN',
      width: '90px',
      render: (row) => <span className="mono">{row.pin}</span>,
    },
    {
      key: 'name',
      header: 'Nama',
      render: (row) => (
        <>
          <div>{row.name}</div>
          <div className="muted mono" style={{ fontSize: 11.5 }}>{orDash(row.employee_code)}</div>
        </>
      ),
    },
    {
      key: 'department',
      header: 'Departemen / jabatan',
      render: (row) => (
        <>
          <div>{orDash(row.department)}</div>
          <div className="muted" style={{ fontSize: 11.5 }}>{orDash(row.position)}</div>
        </>
      ),
    },
    {
      key: 'contact',
      header: 'Kontak',
      render: (row) => (
        <>
          <div style={{ fontSize: 12.5 }}>{orDash(row.email)}</div>
          <div className="muted mono" style={{ fontSize: 11.5 }}>{orDash(row.phone)}</div>
        </>
      ),
    },
    {
      key: 'joined',
      header: 'Masuk',
      render: (row) => (
        <>
          <div>{formatDate(row.joined_at)}</div>
          {row.resigned_at && (
            <div className="muted" style={{ fontSize: 11.5 }}>keluar {formatDate(row.resigned_at)}</div>
          )}
        </>
      ),
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
          <h1>Karyawan</h1>
          <div className="muted" style={{ fontSize: 12.5 }}>
            PIN mencocokkan punch device ke karyawan. Mengubahnya memutus tautan punch lama.
          </div>
        </div>
        <button type="button" className="btn btn--primary btn--sm" onClick={() => setCreating(true)}>
          Tambah karyawan
        </button>
      </div>

      <div className="card">
        <div className="card__body">
          <div className="filters">
            <Field label="Cari">
              <TextInput
                value={search}
                onChange={(value) => {
                  setSearch(value)
                  setOffset(0)
                }}
                placeholder="Nama, PIN, atau kode"
              />
            </Field>
            <Field label="Departemen">
              <Select
                value={department}
                onChange={(value) => {
                  setDepartment(value)
                  setOffset(0)
                }}
                placeholder="Semua departemen"
                options={(departmentsQuery.data ?? []).map((name) => ({ value: name, label: name }))}
              />
            </Field>
            <Field label="Status">
              <Select
                value={isActive}
                onChange={(value) => {
                  setIsActive(value)
                  setOffset(0)
                }}
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
          isEmpty={query.data?.employees.length === 0}
          emptyTitle="Tidak ada karyawan"
          emptyHint="Tambahkan karyawan supaya punch device bisa dicocokkan."
          loadingLabel="Memuat karyawan…"
          onRetry={() => void query.refetch()}
        >
          <DataTable
            rows={query.data?.employees ?? []}
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
                    if (
                      window.confirm(
                        `Hapus karyawan ${row.name} (PIN ${row.pin})?\n\n` +
                          'Punch-nya tidak ikut terhapus, tetapi kehilangan tautan ke karyawan.',
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
            total={query.data?.total ?? 0}
            limit={PAGE_SIZE}
            offset={offset}
            onChange={setOffset}
            disabled={query.isFetching}
          />
        </QueryState>
      </div>

      {creating && (
        <EmployeeFormModal
          onClose={() => setCreating(false)}
          onSaved={(message) => {
            toast.success(message)
            setCreating(false)
            refresh()
          }}
        />
      )}

      {editing && (
        <EmployeeFormModal
          employee={editing}
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

interface EmployeeFormModalProps {
  /** Kosong berarti mode tambah. */
  employee?: EmployeeOut
  onClose: () => void
  onSaved: (message: string) => void
}

function EmployeeFormModal({ employee, onClose, onSaved }: EmployeeFormModalProps) {
  const toast = useToast()
  const isEdit = employee !== undefined

  const [pin, setPin] = useState(employee?.pin ?? '')
  const [name, setName] = useState(employee?.name ?? '')
  const [employeeCode, setEmployeeCode] = useState(employee?.employee_code ?? '')
  const [department, setDepartment] = useState(employee?.department ?? '')
  const [position, setPosition] = useState(employee?.position ?? '')
  const [email, setEmail] = useState(employee?.email ?? '')
  const [phone, setPhone] = useState(employee?.phone ?? '')
  const [joinedAt, setJoinedAt] = useState(employee?.joined_at?.slice(0, 10) ?? '')
  const [resignedAt, setResignedAt] = useState(employee?.resigned_at?.slice(0, 10) ?? '')
  const [isActive, setIsActive] = useState(employee?.is_active ?? true)

  const save = useMutation({
    mutationFn: async () => {
      const base = {
        pin: pin.trim(),
        name: name.trim(),
        employee_code: employeeCode.trim() || null,
        department: department.trim() || null,
        position: position.trim() || null,
        email: email.trim() || null,
        phone: phone.trim() || null,
        joined_at: joinedAt || null,
        is_active: isActive,
      }

      if (!employee) {
        const created = await employeesApi.create(base)
        return `Karyawan ${created.name} (PIN ${created.pin}) dibuat.`
      }

      const result = await employeesApi.update(employee.id, {
        ...base,
        resigned_at: resignedAt || null,
      })
      // Bila PIN berubah, server melaporkan punch yang terputus/tertaut ulang.
      // Itu bagian terpenting dari balasan ini dan tidak boleh diringkas jadi
      // "Perubahan disimpan".
      if (result.unlinked_punches || result.relinked_punches) {
        return (
          `${result.message} ` +
          `Periksa rekap kehadiran pada tanggal-tanggal terkait.`
        )
      }
      return result.message
    },
    onSuccess: (message) => onSaved(message),
    onError: (error) => toast.error(describeError(error)),
  })

  const pinChanged = isEdit && employee !== undefined && pin.trim() !== employee.pin

  return (
    <Modal
      title={isEdit ? `Ubah ${employee?.name}` : 'Tambah karyawan'}
      onClose={onClose}
      busy={save.isPending}
      wide
      footer={
        <>
          <button type="button" className="btn" onClick={onClose} disabled={save.isPending}>
            Batal
          </button>
          <button
            type="button"
            className="btn btn--primary"
            onClick={() => save.mutate()}
            disabled={save.isPending || !pin.trim() || !name.trim()}
          >
            {save.isPending ? 'Menyimpan…' : 'Simpan'}
          </button>
        </>
      }
    >
      <div className="stack">
        <div className="grid grid--2">
          <Field label="PIN" required hint="Harus sama dengan PIN yang terdaftar di device.">
            <TextInput value={pin} onChange={setPin} mono maxLength={24} />
          </Field>
          <Field label="Nama" required>
            <TextInput value={name} onChange={setName} maxLength={128} />
          </Field>
        </div>

        {pinChanged && (
          <div className="login__error" style={{ background: 'var(--warning-soft)', color: 'var(--warning)' }}>
            PIN berubah dari <span className="mono">{employee?.pin}</span> menjadi{' '}
            <span className="mono">{pin}</span>. Punch lama dengan PIN lama akan kehilangan
            tautannya — server akan melaporkan berapa banyak.
          </div>
        )}

        <div className="grid grid--2">
          <Field label="Kode karyawan">
            <TextInput value={employeeCode} onChange={setEmployeeCode} maxLength={32} />
          </Field>
          <Field label="Departemen">
            <TextInput value={department} onChange={setDepartment} maxLength={64} />
          </Field>
        </div>

        <div className="grid grid--2">
          <Field label="Jabatan">
            <TextInput value={position} onChange={setPosition} maxLength={64} />
          </Field>
          <Field label="Telepon">
            <TextInput value={phone} onChange={setPhone} type="tel" maxLength={32} />
          </Field>
        </div>

        <Field label="Email">
          <TextInput value={email} onChange={setEmail} type="email" maxLength={128} />
        </Field>

        <div className="grid grid--2">
          <Field label="Tanggal masuk">
            <TextInput type="date" value={joinedAt} onChange={setJoinedAt} />
          </Field>
          {isEdit && (
            <Field label="Tanggal keluar">
              <TextInput type="date" value={resignedAt} onChange={setResignedAt} />
            </Field>
          )}
        </div>

        <Checkbox checked={isActive} onChange={setIsActive} label="Karyawan aktif" />
      </div>
    </Modal>
  )
}
