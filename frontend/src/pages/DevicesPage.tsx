/**
 * Monitoring device.
 *
 * Pertanyaan yang dijawab layar ini adalah **"device ini kenapa diam?"**.
 * Karena itu kolom yang ditonjolkan bukan sekadar identitas device, melainkan
 * `last_seen_at` (relatif), jumlah perintah yang belum diambil device, dan
 * jumlah punch yang tidak tertaut ke karyawan mana pun — tiga penyebab paling
 * sering dari device yang tampak normal tetapi datanya tidak masuk.
 */

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { ApiError } from '../api/client'
import { devicesApi } from '../api/endpoints'
import type { DeviceOut, DeviceStatus } from '../api/types'
import { DataTable, type Column } from '../components/DataTable'
import { Field, Select, TextInput } from '../components/Field'
import { Modal } from '../components/Modal'
import { Pagination } from '../components/Pagination'
import { DeviceStatusBadge } from '../components/StatusBadge'
import { useToast } from '../components/Toast'
import { QueryState, describeError } from '../components/states'
import { DEVICE_STATUS_OPTIONS } from '../lib/labels'
import { orDash, relativeTime } from '../lib/format'

const PAGE_SIZE = 50

export function DevicesPage() {
  const queryClient = useQueryClient()
  const toast = useToast()

  const [status, setStatus] = useState('')
  const [search, setSearch] = useState('')
  const [offset, setOffset] = useState(0)
  const [editing, setEditing] = useState<DeviceOut | null>(null)

  const query = useQuery({
    queryKey: ['devices', { status, search, offset }],
    queryFn: () =>
      devicesApi.list({
        status: status ? (status as DeviceStatus) : undefined,
        search: search.trim() || undefined,
        limit: PAGE_SIZE,
        offset,
      }),
  })

  const approve = useMutation({
    mutationFn: (deviceId: number) => devicesApi.approve(deviceId),
    onSuccess: (result) => {
      toast.success(result.message)
      void queryClient.invalidateQueries({ queryKey: ['devices'] })
      void queryClient.invalidateQueries({ queryKey: ['dashboard'] })
    },
    onError: (error) => toast.error(describeError(error)),
  })

  const columns: Column<DeviceOut>[] = [
    {
      key: 'serial',
      header: 'Serial number',
      render: (row) => <span className="mono">{row.serial_number}</span>,
    },
    {
      key: 'name',
      header: 'Nama / lokasi',
      render: (row) => (
        <>
          <div>{orDash(row.display_name)}</div>
          {row.location && <div className="muted" style={{ fontSize: 12 }}>{row.location}</div>}
        </>
      ),
    },
    {
      key: 'status',
      header: 'Status',
      render: (row) => <DeviceStatusBadge status={row.status} />,
    },
    {
      key: 'firmware',
      header: 'Model / firmware',
      render: (row) => (
        <>
          <div>{orDash(row.model)}</div>
          <div className="muted" style={{ fontSize: 12 }}>{orDash(row.firmware)}</div>
        </>
      ),
    },
    {
      key: 'tz',
      header: 'Zona waktu',
      render: (row) => <span className="mono">{orDash(row.tz_name)}</span>,
    },
    {
      key: 'last_seen',
      header: 'Terakhir terlihat',
      render: (row) => (
        <>
          <div>{relativeTime(row.last_seen_at)}</div>
          {row.ip_address && <div className="muted mono" style={{ fontSize: 11.5 }}>{row.ip_address}</div>}
        </>
      ),
    },
    {
      key: 'attlog',
      header: 'Punch',
      align: 'right',
      render: (row) => row.attlog_count,
    },
    {
      key: 'pending_commands',
      header: 'Perintah tertunda',
      align: 'right',
      render: (row) =>
        row.pending_commands > 0 ? (
          <span className="badge badge--warn">{row.pending_commands}</span>
        ) : (
          <span className="faint">0</span>
        ),
    },
    {
      key: 'unlinked',
      header: 'Punch tak tertaut',
      align: 'right',
      render: (row) =>
        row.unlinked_punches > 0 ? (
          <span className="badge badge--danger">{row.unlinked_punches}</span>
        ) : (
          <span className="faint">0</span>
        ),
    },
  ]

  return (
    <div className="stack">
      <div className="row row--between">
        <div>
          <h1>Device</h1>
          <div className="muted" style={{ fontSize: 12.5 }}>
            Device yang belum pernah terhubung diletakkan paling akhir.
          </div>
        </div>
        <button
          type="button"
          className="btn btn--sm"
          onClick={() => void query.refetch()}
          disabled={query.isFetching}
        >
          {query.isFetching ? 'Menyegarkan…' : 'Segarkan'}
        </button>
      </div>

      <div className="card">
        <div className="card__body">
          <div className="filters">
            <Field label="Status">
              <Select
                value={status}
                onChange={(value) => {
                  setStatus(value)
                  setOffset(0)
                }}
                options={DEVICE_STATUS_OPTIONS}
                placeholder="Semua status"
              />
            </Field>
            <Field label="Cari">
              <TextInput
                value={search}
                onChange={(value) => {
                  setSearch(value)
                  setOffset(0)
                }}
                placeholder="Serial, nama, atau lokasi"
              />
            </Field>
          </div>
        </div>
      </div>

      <div className="card">
        <QueryState
          isPending={query.isPending}
          error={query.error}
          isEmpty={query.data?.devices.length === 0}
          emptyTitle="Tidak ada device"
          emptyHint="Ubah filter di atas, atau tunggu device pertama melakukan handshake."
          loadingLabel="Memuat daftar device…"
          onRetry={() => void query.refetch()}
        >
          <DataTable
            rows={query.data?.devices ?? []}
            columns={columns}
            rowKey={(row) => row.id}
            actions={(row) => (
              <div className="row" style={{ justifyContent: 'flex-end', flexWrap: 'nowrap' }}>
                {row.status === 'pending' && (
                  <button
                    type="button"
                    className="btn btn--primary btn--sm"
                    disabled={approve.isPending}
                    onClick={() => {
                      if (window.confirm(`Setujui device ${row.serial_number}?`)) {
                        approve.mutate(row.id)
                      }
                    }}
                  >
                    Setujui
                  </button>
                )}
                <button type="button" className="btn btn--sm" onClick={() => setEditing(row)}>
                  Ubah
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

      {editing && (
        <DeviceEditModal
          device={editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null)
            void queryClient.invalidateQueries({ queryKey: ['devices'] })
          }}
        />
      )}
    </div>
  )
}

// --- Formulir ubah device -------------------------------------------------

interface DeviceEditModalProps {
  device: DeviceOut
  onClose: () => void
  onSaved: () => void
}

function DeviceEditModal({ device, onClose, onSaved }: DeviceEditModalProps) {
  const toast = useToast()
  const [displayName, setDisplayName] = useState(device.display_name ?? '')
  const [location, setLocation] = useState(device.location ?? '')
  const [status, setStatus] = useState<string>(device.status)
  const [tzName, setTzName] = useState(device.tz_name ?? '')

  const save = useMutation({
    mutationFn: () =>
      devicesApi.update(device.id, {
        display_name: displayName.trim() || null,
        location: location.trim() || null,
        status: status as DeviceStatus,
        tz_name: tzName.trim() || null,
      }),
    onSuccess: () => {
      toast.success('Device diperbarui.')
      onSaved()
    },
    onError: (error) => toast.error(describeError(error)),
  })

  return (
    <Modal
      title={`Ubah device ${device.serial_number}`}
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
            {save.isPending ? 'Menyimpan…' : 'Simpan'}
          </button>
        </>
      }
    >
      <div className="stack">
        <Field label="Nama tampilan">
          <TextInput value={displayName} onChange={setDisplayName} maxLength={128} />
        </Field>
        <Field label="Lokasi">
          <TextInput value={location} onChange={setLocation} maxLength={191} />
        </Field>
        <Field label="Status">
          <Select value={status} onChange={setStatus} options={DEVICE_STATUS_OPTIONS} />
        </Field>
        <Field
          label="Zona waktu"
          hint="Nama IANA (mis. Asia/Jakarta). Alias WIB/WITA/WIT juga diterima. Zona yang salah menggeser seluruh punch tanpa memunculkan error."
        >
          <TextInput value={tzName} onChange={setTzName} mono maxLength={64} />
        </Field>
        {save.error instanceof ApiError && (
          <div className="login__error">{save.error.message}</div>
        )}
      </div>
    </Modal>
  )
}
