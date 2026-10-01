/**
 * Tabel data generik.
 *
 * Kolom dideklarasikan sebagai data, bukan sebagai JSX yang ditulis ulang di
 * setiap layar. Bedanya terasa saat tabelnya panjang: header, perataan angka,
 * dan kolom aksi hanya ditulis sekali, sehingga tabel kehadiran dan tabel
 * device tidak bisa lagi berbeda gaya tanpa sengaja.
 */

import type { ReactNode } from 'react'

export interface Column<T> {
  /** Kunci unik kolom; tidak harus ada di dalam baris. */
  key: string
  header: ReactNode
  render: (row: T) => ReactNode
  /** `right` untuk angka — memakai `font-variant-numeric: tabular-nums`. */
  align?: 'left' | 'right'
  /** Lebar tetap, mis. `'120px'`; dibiarkan kosong agar tabel mengatur sendiri. */
  width?: string
}

interface DataTableProps<T> {
  rows: T[]
  columns: Column<T>[]
  rowKey: (row: T) => string | number
  /** Kolom aksi di ujung kanan; tidak dibuat bila tidak diberikan. */
  actions?: (row: T) => ReactNode
  /** Header kolom aksi; bawaan "Aksi". */
  actionsHeader?: ReactNode
}

export function DataTable<T>({
  rows,
  columns,
  rowKey,
  actions,
  actionsHeader = 'Aksi',
}: DataTableProps<T>) {
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            {columns.map((column) => (
              <th
                key={column.key}
                className={column.align === 'right' ? 'is-num' : undefined}
                style={column.width ? { width: column.width } : undefined}
              >
                {column.header}
              </th>
            ))}
            {actions && <th className="is-actions">{actionsHeader}</th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={rowKey(row)}>
              {columns.map((column) => (
                <td key={column.key} className={column.align === 'right' ? 'is-num' : undefined}>
                  {column.render(row)}
                </td>
              ))}
              {actions && <td className="is-actions">{actions(row)}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
