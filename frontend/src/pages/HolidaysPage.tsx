/**
 * Hari libur.
 *
 * `is_recurring` berarti tanggalnya diulang setiap tahun (mis. 17 Agustus).
 * Hari raya yang bergeser seperti Idul Fitri **tidak** boleh ditandai berulang —
 * tanggalnya berubah setiap tahun, jadi harus ditambahkan per tahun. Kesalahan
 * di sini membuat seluruh karyawan dianggap tidak hadir pada hari yang
 * sebenarnya libur, dan itu langsung terlihat di rekap.
 */

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { holidaysApi } from '../api/endpoints'
import type { HolidayOut } from '../api/types'
import { DataTable, type Column } from '../components/DataTable'
import { Checkbox, Field, NumberInput, TextInput } from '../components/Field'
import { Modal } from '../components/Modal'
import { Pagination } from '../components/Pagination'
import { Badge } from '../components/StatusBadge'
import { useToast } from '../components/Toast'
import { QueryState, describeError } from '../components/states'
import { formatDate, formatDateLong, todayISO, weekdayName } from '../lib/format'

const PAGE_SIZE = 50

export function HolidaysPage() {
  const queryClient = useQueryClient()
  const toast = useToast()

  const currentYear = Number(todayISO().slice(0, 4))
  const [year, setYear] = useState(String(currentYear))
  const [offset, setOffset] = useState(0)
  const [creating, setCreating] = useState(false)

  const query = useQuery({
    queryKey: ['holidays', { year, offset }],
    queryFn: () =>
      holidaysApi.list({
        year: year.trim() ? Number(year.trim()) : undefined,
        limit: PAGE_SIZE,
        offset,
      }),
  })

  const remove = useMutation({
    mutationFn: (holidayId: number) => holidaysApi.remove(holidayId),
    onSuccess: (result) => {
      toast.success(result.message)
      void queryClient.invalidateQueries({ queryKey: ['holidays'] })
    },
    onError: (error) => toast.error(describeError(error)),
  })

  const columns: Column<HolidayOut>[] = [
    {
      key: 'date',
      header: 'Tanggal',
      render: (row) => (
        <>
          <div>{formatDate(row.holiday_date)}</div>
          <div className="muted" style={{ fontSize: 11.5 }}>{weekdayName(row.holiday_date)}</div>
        </>
      ),
    },
    {
      key: 'name',
      header: 'Keterangan',
      render: (row) => row.name,
    },
    {
      key: 'recurring',
      header: 'Sifat',
      render: (row) =>
        row.is_recurring ? (
          <Badge tone="info">Diulang setiap tahun</Badge>
        ) : (
          <Badge tone="neutral">Sekali saja</Badge>
        ),
    },
  ]

  return (
    <div className="stack">
      <div className="row row--between">
        <div>
          <h1>Hari libur</h1>
          <div className="muted" style={{ fontSize: 12.5 }}>
            Hari libur dikecualikan dari perhitungan tidak hadir dan keterlambatan.
          </div>
        </div>
        <button type="button" className="btn btn--primary btn--sm" onClick={() => setCreating(true)}>
          Tambah hari libur
        </button>
      </div>

      <div className="card">
        <div className="card__body">
          <div className="filters">
            <Field label="Tahun" hint="Kosongkan untuk semua tahun.">
              <NumberInput
                value={year}
                onChange={(value) => {
                  setYear(value)
                  setOffset(0)
                }}
                min={1970}
                max={2999}
              />
            </Field>
          </div>
        </div>
      </div>

      <div className="card">
        <QueryState
          isPending={query.isPending}
          error={query.error}
          isEmpty={query.data?.holidays.length === 0}
          emptyTitle="Belum ada hari libur"
          emptyHint="Tambahkan tanggal merah supaya tidak terhitung sebagai ketidakhadiran."
          loadingLabel="Memuat hari libur…"
          onRetry={() => void query.refetch()}
        >
          <DataTable
            rows={query.data?.holidays ?? []}
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
                      `Hapus hari libur "${row.name}" (${formatDateLong(row.holiday_date)})?`,
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
        <HolidayFormModal
          onClose={() => setCreating(false)}
          onSaved={(message) => {
            toast.success(message)
            setCreating(false)
            void queryClient.invalidateQueries({ queryKey: ['holidays'] })
          }}
        />
      )}
    </div>
  )
}

function HolidayFormModal({
  onClose,
  onSaved,
}: {
  onClose: () => void
  onSaved: (message: string) => void
}) {
  const toast = useToast()
  const [holidayDate, setHolidayDate] = useState(todayISO())
  const [name, setName] = useState('')
  const [isRecurring, setIsRecurring] = useState(false)

  const save = useMutation({
    mutationFn: () =>
      holidaysApi.create({
        holiday_date: holidayDate,
        name: name.trim(),
        is_recurring: isRecurring,
      }),
    onSuccess: (created) => onSaved(`Hari libur "${created.name}" ditambahkan.`),
    onError: (error) => toast.error(describeError(error)),
  })

  return (
    <Modal
      title="Tambah hari libur"
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
            disabled={save.isPending || !name.trim() || !holidayDate}
          >
            {save.isPending ? 'Menyimpan…' : 'Simpan'}
          </button>
        </>
      }
    >
      <div className="stack">
        <Field label="Tanggal" required hint={`Jatuh pada hari ${weekdayName(holidayDate) || '—'}.`}>
          <TextInput type="date" value={holidayDate} onChange={setHolidayDate} />
        </Field>

        <Field label="Keterangan" required hint="mis. Hari Kemerdekaan, Cuti bersama Idul Fitri.">
          <TextInput value={name} onChange={setName} maxLength={128} />
        </Field>

        <Checkbox
          checked={isRecurring}
          onChange={setIsRecurring}
          label="Diulang setiap tahun pada tanggal yang sama"
        />
        <div className="field__hint">
          Jangan tandai untuk hari raya yang tanggalnya bergeser (Idul Fitri, Nyepi, Waisak) —
          tambahkan per tahun.
        </div>
      </div>
    </Modal>
  )
}
