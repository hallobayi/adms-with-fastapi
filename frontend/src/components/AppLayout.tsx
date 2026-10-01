/**
 * Kerangka halaman: bilah samping, bilah atas, dan area isi.
 *
 * Bilah samping dikelompokkan menurut **siapa yang mengerjakannya**, bukan
 * menurut urutan endpoint: hal yang ditunggu keputusan admin (konflik, device
 * pending) diletakkan di kelompok Operasional, sedangkan data yang jarang
 * berubah ada di Data master. Lencana angkanya diambil dari satu panggilan
 * ringkasan yang sama dengan dashboard, jadi angkanya tidak mungkin berbeda
 * antar layar.
 */

import { useQuery } from '@tanstack/react-query'
import { NavLink, Outlet, useLocation } from 'react-router-dom'

import { dashboardApi } from '../api/endpoints'
import { useAuth } from '../auth/AuthContext'

interface NavItem {
  to: string
  label: string
  /** Kunci angka di `DashboardSummary` yang ditampilkan sebagai lencana. */
  badge?: string
  /** Hanya tampil untuk superuser. */
  superuserOnly?: boolean
}

interface NavGroup {
  title: string
  items: NavItem[]
}

export const NAV_GROUPS: NavGroup[] = [
  {
    title: 'Ringkasan',
    items: [{ to: '/', label: 'Dashboard' }],
  },
  {
    title: 'Operasional',
    items: [
      { to: '/devices', label: 'Device', badge: 'devices_pending' },
      { to: '/conflicts', label: 'Konflik', badge: 'unresolved' },
      { to: '/requests', label: 'Arsip request' },
      { to: '/attendance', label: 'Kehadiran' },
    ],
  },
  {
    title: 'Data master',
    items: [
      { to: '/employees', label: 'Karyawan' },
      { to: '/shifts', label: 'Shift' },
      { to: '/assignments', label: 'Penugasan shift' },
      { to: '/holidays', label: 'Hari libur' },
    ],
  },
  {
    title: 'Sistem',
    items: [
      { to: '/accounts', label: 'Akun admin', superuserOnly: true },
      { to: '/password', label: 'Ganti password' },
    ],
  },
]

/** Judul yang ditampilkan di bilah atas untuk sebuah path. */
export function titleForPath(pathname: string): string {
  for (const group of NAV_GROUPS) {
    for (const item of group.items) {
      if (item.to === pathname) return item.label
    }
  }
  return 'Admin'
}

export function AppLayout() {
  const { admin, logout } = useAuth()
  const location = useLocation()

  // Lencana bilah samping. Kegagalannya sengaja **tidak** ditampilkan: ini
  // hiasan, dan bilah samping yang menampilkan galat jauh lebih mengganggu
  // daripada lencana yang tidak muncul.
  const summaryQuery = useQuery({
    queryKey: ['dashboard', 'summary', 1],
    queryFn: () => dashboardApi.summary(1),
    staleTime: 30_000,
    retry: false,
  })
  const summary = summaryQuery.data ?? {}

  async function handleLogout() {
    await logout()
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar__brand">
          <span className="sidebar__brand-mark">A</span>
          <div>
            ADMS
            <small>Attendance Device Management</small>
          </div>
        </div>

        <nav>
          {NAV_GROUPS.map((group) => {
            const items = group.items.filter(
              (item) => !item.superuserOnly || admin?.is_superuser,
            )
            if (items.length === 0) return null
            return (
              <div key={group.title}>
                <div className="sidebar__group">{group.title}</div>
                {items.map((item) => {
                  const count = item.badge ? summary[item.badge] : undefined
                  return (
                    <NavLink
                      key={item.to}
                      to={item.to}
                      end={item.to === '/'}
                      className={({ isActive }) =>
                        isActive ? 'sidebar__link is-active' : 'sidebar__link'
                      }
                    >
                      <span>{item.label}</span>
                      {count ? <span className="sidebar__count">{count}</span> : null}
                    </NavLink>
                  )
                })}
              </div>
            )
          })}
        </nav>
      </aside>

      <div className="main">
        <header className="topbar">
          <div>
            <div className="topbar__title">{titleForPath(location.pathname)}</div>
            <div className="topbar__sub">Panel administrasi ADMS</div>
          </div>
          <div className="topbar__right">
            <div className="topbar__user">
              <strong>{admin?.display_name?.trim() || admin?.username}</strong>
              <span>
                {admin?.username}
                {admin?.is_superuser ? ' · superuser' : ''}
              </span>
            </div>
            <button type="button" className="btn btn--sm" onClick={handleLogout}>
              Keluar
            </button>
          </div>
        </header>

        <main className="content">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
