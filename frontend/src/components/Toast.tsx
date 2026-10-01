/**
 * Notifikasi ringkas di pojok kanan bawah.
 *
 * Dipakai untuk mengabarkan hasil operasi tulis. Prinsipnya: **kegagalan tidak
 * boleh hilang sendiri** — toast galat bertahan sampai ditutup, sedangkan
 * keberhasilan menutup dirinya setelah beberapa detik. Operasi tulis di sini
 * menyentuh data kehadiran dan PIN karyawan, jadi pesan "berhasil" yang lewat
 * begitu saja tanpa terbaca lebih berbahaya daripada pesan yang mengganggu.
 */

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'

export type ToastKind = 'ok' | 'error' | 'info'

interface ToastItem {
  id: number
  kind: ToastKind
  message: string
}

interface ToastApi {
  success: (message: string) => void
  error: (message: string) => void
  info: (message: string) => void
}

const ToastContext = createContext<ToastApi | null>(null)

/** Berapa lama toast keberhasilan bertahan (ms). */
const AUTO_DISMISS_MS = 4500

/** `info` sengaja tanpa varian — tampilannya sama dengan toast biasa. */
function toastClass(kind: ToastKind): string {
  if (kind === 'ok') return 'toast toast--ok'
  if (kind === 'error') return 'toast toast--error'
  return 'toast'
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([])
  const nextId = useRef(1)

  const dismiss = useCallback((id: number) => {
    setItems((current) => current.filter((item) => item.id !== id))
  }, [])

  const push = useCallback(
    (kind: ToastKind, message: string) => {
      const id = nextId.current++
      setItems((current) => [...current, { id, kind, message }])
      // Hanya keberhasilan/informasi yang menutup sendiri.
      if (kind !== 'error') {
        window.setTimeout(() => dismiss(id), AUTO_DISMISS_MS)
      }
    },
    [dismiss],
  )

  const api = useMemo<ToastApi>(
    () => ({
      success: (message) => push('ok', message),
      error: (message) => push('error', message),
      info: (message) => push('info', message),
    }),
    [push],
  )

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {items.map((item) => (
          <div key={item.id} className={toastClass(item.kind)}>
            <div style={{ flex: '1 1 auto' }}>{item.message}</div>
            <button
              type="button"
              className="toast__close"
              aria-label="Tutup"
              onClick={() => dismiss(item.id)}
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

/**
 * Akses API notifikasi.
 *
 * @throws bila dipakai di luar `ToastProvider` — itu kesalahan pemasangan, dan
 *   lebih baik ketahuan saat pengembangan daripada diam-diam tidak menampilkan
 *   apa pun.
 */
export function useToast(): ToastApi {
  const context = useContext(ToastContext)
  if (!context) throw new Error('useToast harus dipakai di dalam <ToastProvider>.')
  return context
}
