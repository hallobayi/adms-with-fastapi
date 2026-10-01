/**
 * Akar aplikasi: penyedia konteks dan peta rute.
 *
 * Urutan penyedianya penting. `QueryClientProvider` berada di luar
 * `AuthProvider` karena auth perlu membersihkan cache kueri saat sesi berakhir.
 * `ToastProvider` berada di luar keduanya supaya galat yang muncul saat memeriksa
 * sesi pun bisa dilaporkan.
 *
 * `basename="/admin"` harus sama dengan `base` di `vite.config.ts` dan
 * `UI_PREFIX` di `app/application.py`. Bila salah satu berbeda, halaman akan
 * tampak kosong tanpa galat apa pun — karena itu ketiganya diberi komentar
 * silang.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'

import { ApiError } from './api/client'
import { AuthProvider } from './auth/AuthContext'
import { AppLayout } from './components/AppLayout'
import { ProtectedRoute, RequireSuperuser } from './components/ProtectedRoute'
import { ToastProvider } from './components/Toast'
import { AccountsPage } from './pages/AccountsPage'
import { AssignmentsPage } from './pages/AssignmentsPage'
import { AttendancePage } from './pages/AttendancePage'
import { ChangePasswordPage } from './pages/ChangePasswordPage'
import { ConflictsPage } from './pages/ConflictsPage'
import { DashboardPage } from './pages/DashboardPage'
import { DevicesPage } from './pages/DevicesPage'
import { EmployeesPage } from './pages/EmployeesPage'
import { HolidaysPage } from './pages/HolidaysPage'
import { LoginPage } from './pages/LoginPage'
import { RequestsPage } from './pages/RequestsPage'
import { ShiftsPage } from './pages/ShiftsPage'

/**
 * Ulangi hanya kegagalan yang mungkin sembuh sendiri.
 *
 * Mengulangi 4xx itu sia-sia: 401 (sesi habis), 403 (tidak berwenang), dan 409
 * (bentrok data) tidak akan berubah hanya karena dicoba lagi — dan mencobanya
 * tiga kali berarti pengguna menunggu tiga kali lebih lama untuk pesan galat
 * yang sama.
 */
function shouldRetry(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false
  return failureCount < 2
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: shouldRetry,
      refetchOnWindowFocus: false,
      staleTime: 10_000,
    },
    mutations: {
      retry: false,
    },
  },
})

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <BrowserRouter basename="/admin">
          <AuthProvider>
            <Routes>
              <Route path="/login" element={<LoginPage />} />

              <Route element={<ProtectedRoute />}>
                <Route element={<AppLayout />}>
                  <Route index element={<DashboardPage />} />
                  <Route path="devices" element={<DevicesPage />} />
                  <Route path="conflicts" element={<ConflictsPage />} />
                  <Route path="requests" element={<RequestsPage />} />
                  <Route path="attendance" element={<AttendancePage />} />

                  <Route path="employees" element={<EmployeesPage />} />
                  <Route path="shifts" element={<ShiftsPage />} />
                  <Route path="assignments" element={<AssignmentsPage />} />
                  <Route path="holidays" element={<HolidaysPage />} />

                  <Route path="password" element={<ChangePasswordPage />} />

                  {/* Layar akun hanya untuk superuser. Server tetap menolak
                      sendiri dengan 403 — ini murni agar admin biasa tidak
                      diarahkan ke layar yang pasti gagal. */}
                  <Route element={<RequireSuperuser />}>
                    <Route path="accounts" element={<AccountsPage />} />
                  </Route>
                </Route>
              </Route>

              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </AuthProvider>
        </BrowserRouter>
      </ToastProvider>
    </QueryClientProvider>
  )
}
