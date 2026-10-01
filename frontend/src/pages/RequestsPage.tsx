/**
 * Arsip request mentah dari device.
 *
 * Layar ini adalah tempat terakhir untuk menjawab "device sebenarnya mengirim
 * apa?". Karena itu detailnya menampilkan **body mentah apa adanya** — bukan
 * ringkasan hasil parsing. Kalau angka `parsed_count` dan `stored_count`
 * berbeda, body mentah itulah satu-satunya bukti yang bisa dipercaya.
 */

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { requestsApi } from '../api/endpoints'
import type { RequestOut } from '../api/types'
import { DataTable, type Column } from '../components/DataTable'
import { Field, Select, TextInput } from '../components/Field'
import { Modal } from '../components/Modal'
import { Pagination } from '../components/Pagination'
import { ProcessStatusBadge } from '../components/StatusBadge'
import { QueryState } from '../components/states'
import { formatBytes, formatDateTime, orDash } from '../lib/format'

const PAGE_SIZE = 50

const PROCESS_OPTIONS = [
  { value: 'received', label: 'Diterima' },
  { value: 'processed', label: 'Diproses' },
  { value: 'failed', label: 'Gagal' },
  { value: 'skipped', label: 'Dilewati' },
]

export function RequestsPage() {
  const [serialNumber, setSerialNumber] = useState('')
  const [tableName, setTableName] = useState('')
  const [processStatus, setProcessStatus] = useState('')
  const [since, setSince] = useState('')
  const [offset, setOffset] = useState(0)
  const [detail, setDetail] = useState<RequestOut | null>(null)

  const query = useQuery({
    queryKey: ['requests', { serialNumber, tableName, processStatus, since, offset }],
    queryFn: () =>
      requestsApi.list({
        serial_number: serialNumber.trim() || undefined,
        table_name: tableName.trim() || undefined,
        process_status: processStatus || undefined,
        since: since.trim() || undefined,
        limit: PAGE_SIZE,
        offset,
      }),
  })

  function resetTo(patch: () => void) {
    patch()
    setOffset(0)
  }

  const columns: Column<RequestOut>[] = [
    { key: 'id', header: 'ID', align: 'right', width: '70px', render: (row) => row.id },
    {
      key: 'created',
      header: 'Diterima',
      render: (row) => (
        <>
          <div>{formatDateTime(row.created_at)}</div>
          {row.source_ip && (
            <div className="muted mono" style={{ fontSize: 11.5 }}>
              {row.source_ip}
            </div>
          )}
        </>
      ),
    },
    {
      key: 'serial',
      header: 'Serial',
      render: (row) => <span className="mono">{row.serial_number}</span>,
    },
    {
      key: 'endpoint',
      header: 'Endpoint',
      render: (row) => (
        <>
          <div className="mono">{row.http_method} {row.endpoint}</div>
          <div className="muted" style={{ fontSize: 12 }}>{orDash(row.table_name)}</div>
        </>
      ),
    },
    {
      key: 'body',
      header: 'Ukuran',
      align: 'right',
      render: (row) => (
        <>
          <div>{formatBytes(row.body_bytes)}</div>
          <div className="muted" style={{ fontSize: 11.5 }}>{row.line_count} baris</div>
        </>
      ),
    },
    {
      key: 'counts',
      header: 'Disimpan / duplikat / gagal',
      align: 'right',
      render: (row) => (
        <>
          <div>{row.stored_count}</div>
          <div style={{ fontSize: 11.5 }}>
            {row.dup_count > 0 && <span className="badge badge--warn">{row.dup_count} dup</span>}{' '}
            {row.failed_count > 0 && <span className="badge badge--danger">{row.failed_count} gagal</span>}
            {row.dup_count === 0 && row.failed_count === 0 && <span className="faint">—</span>}
          </div>
        </>
      ),
    },
    {
      key: 'status',
      header: 'Status',
      render: (row) => (
        <>
          <ProcessStatusBadge status={row.process_status} />
          {row.error_message && (
            <div className="muted" style={{ fontSize: 11.5, marginTop: 3 }}>{row.error_message}</div>
          )}
        </>
      ),
    },
  ]

  return (
    <div className="stack">
      <div className="row row--between">
        <div>
          <h1>Arsip request</h1>
          <div className="muted" style={{ fontSize: 12.5 }}>
            Body mentah tidak dikirim pada daftar — buka detail untuk melihatnya.
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
            <Field label="Serial number">
              <TextInput
                value={serialNumber}
                onChange={(value) => resetTo(() => setSerialNumber(value))}
                mono
                placeholder="mis. 1234567890"
              />
            </Field>
            <Field label="Tabel">
              <TextInput
                value={tableName}
                onChange={(value) => resetTo(() => setTableName(value))}
                mono
                placeholder="mis. ATTLOG"
              />
            </Field>
            <Field label="Status proses">
              <Select
                value={processStatus}
                onChange={(v) => resetTo(() => setProcessStatus(v))}
                options={PROCESS_OPTIONS}
                placeholder="Semua status"
              />
            </Field>
            <Field label="Sejak" hint="ISO-8601, mis. 2026-09-30 00:00:00">
              <TextInput
                value={since}
                onChange={(value) => resetTo(() => setSince(value))}
                mono
                placeholder="2026-09-30 00:00:00"
              />
            </Field>
          </div>
        </div>
      </div>

      <div className="card">
        <QueryState
          isPending={query.isPending}
          error={query.error}
          isEmpty={query.data?.requests.length === 0}
          emptyTitle="Tidak ada request"
          emptyHint="Tidak ada arsip yang cocok dengan filter ini."
          loadingLabel="Memuat arsip request…"
          onRetry={() => void query.refetch()}
        >
          <DataTable
            rows={query.data?.requests ?? []}
            columns={columns}
            rowKey={(row) => row.id}
            actions={(row) => (
              <button type="button" className="btn btn--sm" onClick={() => setDetail(row)}>
                Detail
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

      {detail && <RequestDetailModal requestId={detail.id} onClose={() => setDetail(null)} />}
    </div>
  )
}

/**
 * Detail satu request.
 *
 * Body diambil **saat dibuka**, bukan ikut pada daftar: arsip bisa mencapai
 * 1 MB per baris, dan memuat 50 di antaranya sekaligus untuk sekadar
 * menampilkan daftar adalah pemborosan yang langsung terasa.
 */
function RequestDetailModal({ requestId, onClose }: { requestId: number; onClose: () => void }) {
  const query = useQuery({
    queryKey: ['requests', 'detail', requestId],
    queryFn: () => requestsApi.get(requestId),
    staleTime: 60_000,
  })

  return (
    <Modal title={`Request #${requestId}`} onClose={onClose} wide
      footer={<button type="button" className="btn" onClick={onClose}>Tutup</button>}
    >
      <QueryState
        isPending={query.isPending}
        error={query.error}
        loadingLabel="Memuat detail…"
        onRetry={() => void query.refetch()}
      >
        {query.data && (
          <div className="stack">
            <dl className="kv">
              <dt>Device</dt>
              <dd className="mono">{query.data.serial_number}</dd>
              <dt>Endpoint</dt>
              <dd className="mono">{query.data.http_method} {query.data.endpoint}</dd>
              <dt>Tabel</dt>
              <dd>{orDash(query.data.table_name)}</dd>
              <dt>Diterima</dt>
              <dd>{formatDateTime(query.data.created_at)}</dd>
              <dt>Selesai diproses</dt>
              <dd>{formatDateTime(query.data.processed_at)}</dd>
              <dt>Ukuran</dt>
              <dd>
                {formatBytes(query.data.body_bytes)} · {query.data.line_count} baris ·{' '}
                {query.data.parsed_count} terbaca · {query.data.stored_count} disimpan ·{' '}
                {query.data.dup_count} duplikat · {query.data.failed_count} gagal
              </dd>
              <dt>Status</dt>
              <dd><ProcessStatusBadge status={query.data.process_status} /></dd>
              {query.data.error_message && (
                <>
                  <dt>Galat</dt>
                  <dd>{query.data.error_message}</dd>
                </>
              )}
            </dl>

            <div>
              <div className="field__label" style={{ marginBottom: 6 }}>
                Body mentah
              </div>
              {query.data.body_raw ? (
                <pre className="code">{query.data.body_raw}</pre>
              ) : (
                <div className="muted" style={{ fontSize: 12.5 }}>
                  Request ini tidak menyimpan body.
                </div>
              )}
            </div>
          </div>
        )}
      </QueryState>
    </Modal>
  )
}
