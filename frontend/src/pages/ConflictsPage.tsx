/**
 * Antrean konflik sinkronisasi.
 *
 * Tidak ada tombol "selesaikan semua" — itu keputusan desain server, dan layar
 * ini mengikutinya. Setiap baris harus dibuka dan diputuskan satu per satu,
 * karena keputusan "pakai versi server" atau "pakai versi device" berarti
 * memilih data mana yang dianggap benar; membiarkan itu terjadi massal tanpa
 * ditinjau adalah cara kehilangan data tanpa jejak.
 *
 * Karena itu formulir keputusannya juga **mewajibkan** catatan: alasan
 * keputusan ikut tersimpan di `sync_log`, dan itulah satu-satunya jejak siapa
 * memutuskan apa.
 */

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { conflictsApi } from '../api/endpoints'
import type { ConflictOut, ConflictResolution } from '../api/types'
import { DataTable, type Column } from '../components/DataTable'
import { Field, Select, Textarea, TextInput } from '../components/Field'
import { Modal } from '../components/Modal'
import { Pagination } from '../components/Pagination'
import { Badge } from '../components/StatusBadge'
import { useToast } from '../components/Toast'
import { QueryState, describeError } from '../components/states'
import {
  CONFLICT_ENTITY_LABELS,
  CONFLICT_RESOLUTION_LABELS,
  CONFLICT_RESOLUTION_OPTIONS,
} from '../lib/labels'
import { formatDateTime, orDash } from '../lib/format'

const PAGE_SIZE = 50

/** Pilihan cakupan; `undefined` berarti semua (server mengabaikan filter). */
type Scope = 'queue' | 'resolved' | 'all'

const SCOPE_OPTIONS = [
  { value: 'queue' as Scope, label: 'Belum ditinjau' },
  { value: 'resolved' as Scope, label: 'Sudah diputuskan' },
  { value: 'all' as Scope, label: 'Semua' },
]

export function ConflictsPage() {
  const queryClient = useQueryClient()
  const toast = useToast()

  const [scope, setScope] = useState<Scope>('queue')
  const [serialNumber, setSerialNumber] = useState('')
  const [entityType, setEntityType] = useState('')
  const [offset, setOffset] = useState(0)
  const [resolving, setResolving] = useState<ConflictOut | null>(null)

  const query = useQuery({
    queryKey: ['conflicts', { scope, serialNumber, entityType, offset }],
    queryFn: () =>
      conflictsApi.list({
        resolved: scope === 'all' ? undefined : scope === 'resolved',
        serial_number: serialNumber.trim() || undefined,
        entity_type: entityType.trim() || undefined,
        limit: PAGE_SIZE,
        offset,
      }),
  })

  function changeScope(next: Scope) {
    setScope(next)
    setOffset(0)
  }

  const columns: Column<ConflictOut>[] = [
    { key: 'id', header: 'ID', align: 'right', width: '70px', render: (row) => row.id },
    {
      key: 'created',
      header: 'Tercatat',
      render: (row) => formatDateTime(row.created_at),
    },
    {
      key: 'serial',
      header: 'Device',
      render: (row) => <span className="mono">{row.serial_number}</span>,
    },
    {
      key: 'entity',
      header: 'Entitas',
      render: (row) => (
        <>
          <div>{CONFLICT_ENTITY_LABELS[row.entity_type] ?? row.entity_type}</div>
          <div className="muted mono" style={{ fontSize: 11.5 }}>
            {orDash(row.pin)}
            {row.finger_index !== null && row.finger_index !== undefined
              ? ` · jari ${row.finger_index}`
              : ''}
          </div>
        </>
      ),
    },
    {
      key: 'action',
      header: 'Aksi device',
      render: (row) => <span className="mono">{row.action}</span>,
    },
    {
      key: 'detail',
      header: 'Rincian konflik',
      render: (row) => (
        <span className="muted" style={{ fontSize: 12.5 }}>{orDash(row.conflict_detail)}</span>
      ),
    },
    {
      key: 'resolved_by',
      header: 'Keputusan',
      render: (row) =>
        row.resolved_by === 'none' ? (
          <Badge tone="warn">Menunggu</Badge>
        ) : (
          <Badge tone="ok">{CONFLICT_RESOLUTION_LABELS[row.resolved_by] ?? row.resolved_by}</Badge>
        ),
    },
  ]

  return (
    <div className="stack">
      <div className="row row--between">
        <div>
          <h1>Konflik</h1>
          <div className="muted" style={{ fontSize: 12.5 }}>
            Baris yang kalah tidak pernah dihapus — hanya ditandai tidak valid, agar jejaknya
            bisa ditelusuri.
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
          <div className="row" style={{ marginBottom: 14 }}>
            {SCOPE_OPTIONS.map((option) => (
              <button
                key={option.value}
                type="button"
                className={scope === option.value ? 'btn btn--primary btn--sm' : 'btn btn--sm'}
                onClick={() => changeScope(option.value)}
              >
                {option.label}
              </button>
            ))}
          </div>
          <div className="filters">
            <Field label="Serial number">
              <TextInput
                value={serialNumber}
                onChange={(value) => {
                  setSerialNumber(value)
                  setOffset(0)
                }}
                mono
              />
            </Field>
            <Field label="Jenis entitas">
              <Select
                value={entityType}
                onChange={(value) => {
                  setEntityType(value)
                  setOffset(0)
                }}
                placeholder="Semua entitas"
                options={Object.entries(CONFLICT_ENTITY_LABELS).map(([value, label]) => ({
                  value,
                  label,
                }))}
              />
            </Field>
          </div>
        </div>
      </div>

      <div className="card">
        <QueryState
          isPending={query.isPending}
          error={query.error}
          isEmpty={query.data?.conflicts.length === 0}
          emptyTitle={scope === 'queue' ? 'Tidak ada konflik menunggu' : 'Tidak ada konflik'}
          emptyHint={
            scope === 'queue'
              ? 'Semua konflik sudah ditinjau. Bagus.'
              : 'Tidak ada data yang cocok dengan filter ini.'
          }
          loadingLabel="Memuat konflik…"
          onRetry={() => void query.refetch()}
        >
          <DataTable
            rows={query.data?.conflicts ?? []}
            columns={columns}
            rowKey={(row) => row.id}
            actions={(row) =>
              row.resolved_by === 'none' ? (
                <button
                  type="button"
                  className="btn btn--primary btn--sm"
                  onClick={() => setResolving(row)}
                >
                  Putuskan
                </button>
              ) : (
                <span className="faint">—</span>
              )
            }
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

      {resolving && (
        <ResolveModal
          conflict={resolving}
          onClose={() => setResolving(null)}
          onResolved={(message) => {
            toast.success(message)
            setResolving(null)
            void queryClient.invalidateQueries({ queryKey: ['conflicts'] })
            void queryClient.invalidateQueries({ queryKey: ['dashboard'] })
          }}
        />
      )}
    </div>
  )
}

interface ResolveModalProps {
  conflict: ConflictOut
  onClose: () => void
  onResolved: (message: string) => void
}

function ResolveModal({ conflict, onClose, onResolved }: ResolveModalProps) {
  const toast = useToast()
  const [resolution, setResolution] = useState<ConflictResolution>('server_wins')
  const [note, setNote] = useState('')

  const resolve = useMutation({
    mutationFn: () => conflictsApi.resolve(conflict.id, resolution, note),
    onSuccess: (result) => onResolved(result.message),
    onError: (error) => toast.error(describeError(error)),
  })

  const noteMissing = note.trim().length === 0

  return (
    <Modal
      title={`Putuskan konflik #${conflict.id}`}
      onClose={onClose}
      busy={resolve.isPending}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose} disabled={resolve.isPending}>
            Batal
          </button>
          <button
            type="button"
            className="btn btn--primary"
            onClick={() => resolve.mutate()}
            disabled={resolve.isPending || noteMissing}
            title={noteMissing ? 'Catatan wajib diisi' : undefined}
          >
            {resolve.isPending ? 'Menerapkan…' : 'Terapkan keputusan'}
          </button>
        </>
      }
    >
      <div className="stack">
        <dl className="kv">
          <dt>Device</dt>
          <dd className="mono">{conflict.serial_number}</dd>
          <dt>Entitas</dt>
          <dd>
            {CONFLICT_ENTITY_LABELS[conflict.entity_type] ?? conflict.entity_type}
            {conflict.pin ? ` · PIN ${conflict.pin}` : ''}
            {conflict.finger_index !== null && conflict.finger_index !== undefined
              ? ` · jari ${conflict.finger_index}`
              : ''}
          </dd>
          <dt>Aksi device</dt>
          <dd className="mono">{conflict.action}</dd>
          <dt>Rincian</dt>
          <dd>{orDash(conflict.conflict_detail)}</dd>
          <dt>Tercatat</dt>
          <dd>{formatDateTime(conflict.created_at)}</dd>
        </dl>

        <Field
          label="Keputusan"
          hint="Versi yang tidak dipilih akan ditandai tidak valid (is_valid = 0), tidak dihapus."
          required
        >
          <Select
            value={resolution}
            onChange={(value) => setResolution(value as ConflictResolution)}
            options={CONFLICT_RESOLUTION_OPTIONS}
          />
        </Field>

        <Field
          label="Alasan"
          hint="Ikut tercatat di sync_log — inilah satu-satunya jejak siapa memutuskan apa."
          required
        >
          <Textarea
            value={note}
            onChange={setNote}
            rows={3}
            maxLength={255}
            placeholder="mis. Data di server sudah dikoreksi manual oleh HRD."
          />
        </Field>
      </div>
    </Modal>
  )
}
