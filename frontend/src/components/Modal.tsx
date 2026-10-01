/**
 * Dialog modal.
 *
 * Dipakai untuk formulir tambah/ubah dan konfirmasi hapus. Dua hal yang
 * ditangani di sini dan mudah terlupa:
 *
 * - **Tombol Escape menutup dialog.** Tanpa itu, pengguna keyboard terjebak.
 * - **Selama dialog terbuka, halaman di belakang tidak ikut menggulir.** Kalau
 *   tidak dikunci, roda tetikus akan menggulir latar yang tidak terlihat.
 *
 * Dialog sengaja **tidak** menutup diri saat diklik di luar bila `busy` benar:
 * operasi tulis yang sedang berjalan tidak boleh dibatalkan tanpa sengaja.
 */

import { useEffect, type ReactNode } from 'react'

interface ModalProps {
  title: string
  onClose: () => void
  children: ReactNode
  footer?: ReactNode
  /** Lebar lebih besar untuk konten yang butuh ruang, mis. body mentah. */
  wide?: boolean
  /** Saat true, klik latar dan Escape diabaikan. */
  busy?: boolean
}

export function Modal({ title, onClose, children, footer, wide, busy }: ModalProps) {
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape' && !busy) onClose()
    }
    document.addEventListener('keydown', onKeyDown)

    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    return () => {
      document.removeEventListener('keydown', onKeyDown)
      document.body.style.overflow = previousOverflow
    }
  }, [onClose, busy])

  return (
    <div
      className="modal-backdrop"
      onMouseDown={(event) => {
        // Hanya klik yang **mulai** di latar yang menutup; menyeret teks dari
        // dalam dialog lalu melepas tombol di latar tidak boleh menutupnya.
        if (event.target === event.currentTarget && !busy) onClose()
      }}
    >
      <div
        className={wide ? 'modal modal--wide' : 'modal'}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <div className="modal__header">
          <h2>{title}</h2>
          <button
            type="button"
            className="btn btn--ghost btn--sm"
            onClick={onClose}
            disabled={busy}
            aria-label="Tutup"
          >
            ×
          </button>
        </div>
        <div className="modal__body">{children}</div>
        {footer && <div className="modal__footer">{footer}</div>}
      </div>
    </div>
  )
}
