/**
 * Penjaga rute.
 *
 * Selama status sesi masih `unknown`, yang ditampilkan adalah indikator
 * memuat — **bukan** pengalihan ke halaman masuk. Mengalihkan lebih dulu akan
 * membuat admin yang sesinya masih sah melihat halaman login berkedip setiap
 * kali menekan F5, dan itu membuat mereka mengira sesinya bermasalah.
 */

import { Navigate, Outlet, useLocation } from 'react-router-dom'

import { useAuth } from '../auth/AuthContext'
import { LoadingState } from './states'

export function ProtectedRoute() {
  const { status } = useAuth()
  const location = useLocation()

  if (status === 'unknown') {
    return (
      <div style={{ display: 'grid', placeItems: 'center', minHeight: '100vh' }}>
        <LoadingState label="Memeriksa sesi…" />
      </div>
    )
  }

  if (status === 'anonymous') {
    // `state.from` dipakai halaman masuk untuk mengembalikan admin ke halaman
    // yang tadi ingin dibuka, bukan selalu ke dashboard.
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />
  }

  return <Outlet />
}

/**
 * Penjaga tambahan untuk rute yang hanya boleh dibuka superuser.
 *
 * Ini **bukan** pengganti pemeriksaan di server — `/api/admin/accounts`
 * menolak sendiri dengan 403. Tujuannya murni agar admin biasa tidak diarahkan
 * ke layar yang pasti gagal.
 */
export function RequireSuperuser() {
  const { admin } = useAuth()
  if (admin && !admin.is_superuser) return <Navigate to="/" replace />
  return <Outlet />
}
