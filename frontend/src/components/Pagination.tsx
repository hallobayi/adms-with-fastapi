/**
 * Navigasi halaman untuk daftar yang dipenggal server.
 *
 * Server membatasi `limit` (mis. 200 untuk penugasan, 50 untuk konflik), jadi
 * tanpa kendali ini admin akan mengira datanya habis padahal masih ada. Teks
 * rentangnya ("1–50 dari 312") ditulis eksplisit supaya tidak ada keraguan
 * berapa yang sedang dilihat.
 */

interface PaginationProps {
  total: number
  limit: number
  offset: number
  onChange: (offset: number) => void
  /** Nonaktifkan tombol saat kueri sedang berjalan. */
  disabled?: boolean
}

export function Pagination({ total, limit, offset, onChange, disabled }: PaginationProps) {
  if (total <= limit) return null

  const first = total === 0 ? 0 : offset + 1
  const last = Math.min(offset + limit, total)
  const hasPrev = offset > 0
  const hasNext = offset + limit < total

  return (
    <div className="pagination">
      <span>
        Menampilkan <strong>{first}</strong>–<strong>{last}</strong> dari{' '}
        <strong>{total}</strong>
      </span>
      <div className="pagination__buttons">
        <button
          type="button"
          className="btn btn--sm"
          disabled={disabled || !hasPrev}
          onClick={() => onChange(Math.max(0, offset - limit))}
        >
          ← Sebelumnya
        </button>
        <button
          type="button"
          className="btn btn--sm"
          disabled={disabled || !hasNext}
          onClick={() => onChange(offset + limit)}
        >
          Berikutnya →
        </button>
      </div>
    </div>
  )
}
