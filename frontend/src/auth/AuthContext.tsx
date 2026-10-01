/**
 * Keadaan sesi admin.
 *
 * Sesi disimpan server sebagai cookie HttpOnly, jadi klien **tidak bisa tahu**
 * apakah ia sedang login tanpa bertanya. Karena itu status awalnya `unknown`,
 * bukan `anonymous`: membedakan keduanya penting agar halaman login tidak
 * berkedip sekejap setiap kali halaman dimuat ulang.
 *
 * Tiga keadaan itu bermakna berbeda:
 *
 * - `unknown` — belum tahu; tampilkan indikator memuat, jangan mengalihkan.
 * - `anonymous` — sudah dipastikan belum login; arahkan ke halaman masuk.
 * - `authenticated` — sesi sah; `admin` terisi.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { useQueryClient } from '@tanstack/react-query'

import { ApiError, onUnauthorized } from '../api/client'
import { authApi } from '../api/endpoints'
import type { AdminMe } from '../api/types'

export type AuthStatus = 'unknown' | 'anonymous' | 'authenticated'

interface AuthContextValue {
  status: AuthStatus
  admin: AdminMe | null
  login: (username: string, password: string) => Promise<void>
  logout: () => Promise<void>
  /** Paksa muat ulang identitas, mis. setelah data admin berubah. */
  refresh: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>('unknown')
  const [admin, setAdmin] = useState<AdminMe | null>(null)
  const queryClient = useQueryClient()

  const applyAdmin = useCallback((next: AdminMe | null) => {
    setAdmin(next)
    setStatus(next ? 'authenticated' : 'anonymous')
  }, [])

  const refresh = useCallback(async () => {
    try {
      applyAdmin(await authApi.me())
    } catch (error) {
      // 401 berarti belum login — itu jawaban yang sah, bukan kegagalan.
      if (error instanceof ApiError && error.status === 401) {
        applyAdmin(null)
        return
      }
      // Galat lain (server mati, jaringan putus) tetap dianggap belum login,
      // tetapi statusnya tidak dipaksa: halaman akan menampilkan galatnya.
      applyAdmin(null)
    }
  }, [applyAdmin])

  // Periksa sesi sekali saat aplikasi dimuat.
  useEffect(() => {
    void refresh()
  }, [refresh])

  // Sesi bisa habis di tengah pemakaian; saat itu terjadi, bersihkan keadaan
  // dan seluruh cache kueri supaya tidak ada data lama yang tertinggal di
  // layar setelah pengguna berikutnya masuk.
  useEffect(() => {
    return onUnauthorized(() => {
      setAdmin(null)
      setStatus('anonymous')
      queryClient.clear()
    })
  }, [queryClient])

  const login = useCallback(
    async (username: string, password: string) => {
      const result = await authApi.login(username, password)
      applyAdmin(result.admin)
      // Cache dari sesi sebelumnya (bila ada) tidak boleh terbawa.
      queryClient.clear()
    },
    [applyAdmin, queryClient],
  )

  const logout = useCallback(async () => {
    try {
      await authApi.logout()
    } finally {
      // Apa pun hasilnya, klien menganggap dirinya keluar. Kalau permintaan
      // gagal, sesi di server mungkin masih hidup — tetapi menahan pengguna di
      // dalam aplikasi karena itu justru lebih buruk.
      applyAdmin(null)
      queryClient.clear()
    }
  }, [applyAdmin, queryClient])

  const value = useMemo<AuthContextValue>(
    () => ({ status, admin, login, logout, refresh }),
    [status, admin, login, logout, refresh],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth harus dipakai di dalam <AuthProvider>.')
  return context
}

/**
 * Identitas admin yang dijamin ada.
 *
 * Dipakai di dalam rute yang sudah dilindungi, sehingga `admin` pasti terisi.
 * Pemeriksaan ini ada supaya komponen tidak perlu menulis `admin!` di mana-mana
 * — dan bila suatu saat urutan provider berubah, kegagalannya jelas.
 */
export function useCurrentAdmin(): AdminMe {
  const { admin } = useAuth()
  if (!admin) throw new Error('useCurrentAdmin dipakai di luar rute terproteksi.')
  return admin
}
