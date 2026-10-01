/**
 * Keadaan memuat / galat / kosong, plus satu pembungkus yang memilihnya.
 *
 * Hampir setiap layar di antarmuka ini punya bentuk yang sama: panggil API,
 * lalu tampilkan salah satu dari empat hal — memuat, galat, kosong, atau isi.
 * Menuliskan percabangan itu di sebelas berkas berarti sebelas kesempatan untuk
 * lupa menangani salah satunya. `<QueryState>` di bawah memusatkannya.
 */

import type { ReactNode } from 'react'

import { ApiError } from '../api/client'

export function Spinner() {
  return <span className="spinner" aria-hidden="true" />
}

export function LoadingState({ label = 'Memuat…' }: { label?: string }) {
  return (
    <div className="state">
      <Spinner />
      <div className="state__hint" style={{ marginTop: 10 }}>
        {label}
      </div>
    </div>
  )
}

/**
 * Ubah nilai `error` apa pun menjadi kalimat yang bisa dibaca.
 *
 * `ApiError` sudah membawa pesan dari server; sisanya (galat jaringan, bug)
 * ditampilkan apa adanya agar tidak menyembunyikan masalah nyata.
 */
export function describeError(error: unknown): string {
  if (error instanceof ApiError) return error.message
  if (error instanceof Error) return error.message
  if (typeof error === 'string') return error
  return 'Terjadi kesalahan yang tidak terduga.'
}

export function ErrorState({
  error,
  onRetry,
}: {
  error: unknown
  onRetry?: () => void
}) {
  return (
    <div className="state state--error">
      <div className="state__title">Gagal memuat data</div>
      <div className="state__hint">{describeError(error)}</div>
      {onRetry && (
        <div style={{ marginTop: 14 }}>
          <button type="button" className="btn btn--sm" onClick={onRetry}>
            Coba lagi
          </button>
        </div>
      )}
    </div>
  )
}

export function EmptyState({
  title = 'Belum ada data',
  hint,
  action,
}: {
  title?: string
  hint?: string
  action?: ReactNode
}) {
  return (
    <div className="state">
      <div className="state__title">{title}</div>
      {hint && <div className="state__hint">{hint}</div>}
      {action && <div style={{ marginTop: 14 }}>{action}</div>}
    </div>
  )
}

interface QueryStateProps {
  isPending: boolean
  error: unknown
  /** Bila diisi, keadaan kosong ditampilkan saat `isEmpty` benar. */
  isEmpty?: boolean
  emptyTitle?: string
  emptyHint?: string
  loadingLabel?: string
  onRetry?: () => void
  /** Isi yang ditampilkan bila semuanya beres dan tidak kosong. */
  children: ReactNode
}

/**
 * Pilih satu dari empat keadaan untuk sebuah kueri.
 *
 * Urutan pemeriksaannya disengaja: **galat lebih dulu daripada memuat**, karena
 * TanStack Query bisa melaporkan keduanya sekaligus saat mencoba ulang — dan
 * menampilkan "memuat" tanpa henti pada permintaan yang selalu gagal adalah
 * cara paling mudah membuat admin mengira sistemnya menggantung.
 */
export function QueryState({
  isPending,
  error,
  isEmpty = false,
  emptyTitle,
  emptyHint,
  loadingLabel,
  onRetry,
  children,
}: QueryStateProps) {
  if (error) return <ErrorState error={error} onRetry={onRetry} />
  if (isPending) return <LoadingState label={loadingLabel} />
  if (isEmpty) return <EmptyState title={emptyTitle} hint={emptyHint} />
  return <>{children}</>
}
