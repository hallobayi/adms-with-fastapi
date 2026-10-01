/**
 * Halaman masuk.
 *
 * Pesan galat ditampilkan **di dalam** kartu, bukan sebagai notifikasi: saat
 * login gagal, satu-satunya hal yang perlu dibaca pengguna adalah alasan
 * kegagalannya, dan itu tidak boleh muncul di pojok layar yang bisa terlewat.
 */

import { useState, type FormEvent } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'

import { useAuth } from '../auth/AuthContext'
import { Field, TextInput } from '../components/Field'
import { LoadingState, describeError } from '../components/states'

interface LocationState {
  from?: string
}

export function LoginPage() {
  const { status, login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  // Sudah login? Jangan tahan di sini.
  if (status === 'authenticated') return <Navigate to="/" replace />
  if (status === 'unknown') {
    return (
      <div className="login">
        <LoadingState label="Memeriksa sesi…" />
      </div>
    )
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (busy) return

    setBusy(true)
    setError(null)
    try {
      await login(username.trim(), password)
      const target = (location.state as LocationState | null)?.from
      navigate(target && target !== '/login' ? target : '/', { replace: true })
    } catch (caught) {
      setError(describeError(caught))
      setPassword('')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login">
      <div className="login__card">
        <div className="login__brand">
          <span className="login__brand-mark">A</span>
          <div>
            <div style={{ fontWeight: 600 }}>ADMS Admin</div>
            <div className="muted" style={{ fontSize: 12 }}>
              Attendance Device Management
            </div>
          </div>
        </div>

        <form className="login__form" onSubmit={handleSubmit}>
          {error && <div className="login__error">{error}</div>}

          <Field label="Username" required>
            <TextInput
              value={username}
              onChange={setUsername}
              autoComplete="username"
              autoFocus
              disabled={busy}
              maxLength={64}
            />
          </Field>

          <Field label="Password" required>
            <TextInput
              value={password}
              onChange={setPassword}
              type="password"
              autoComplete="current-password"
              disabled={busy}
              maxLength={1024}
            />
          </Field>

          <button type="submit" className="btn btn--primary" disabled={busy || !username || !password}>
            {busy ? 'Memproses…' : 'Masuk'}
          </button>
        </form>

        <div className="login__note">
          Sesi disimpan sebagai cookie HttpOnly. Akun pertama hanya bisa dibuat lewat kode
          (<code>auth.create_admin</code>).
        </div>
      </div>
    </div>
  )
}
