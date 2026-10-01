/**
 * Ganti password sendiri.
 *
 * Server mencabut **seluruh** sesi setelah password diganti — termasuk sesi
 * yang sedang dipakai. Itu disengaja: alasan orang mengganti password biasanya
 * justru "saya tidak yakin siapa lagi yang punya akses", dan membiarkan sesi
 * lama hidup membuat tindakan itu tidak ada gunanya.
 *
 * Karena itu layar ini berakhir dengan pengalihan ke halaman masuk, bukan
 * dengan pesan "berhasil" yang membingungkan karena pengguna lalu terlempar
 * sendiri beberapa detik kemudian.
 */

import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'

import { authApi } from '../api/endpoints'
import { useAuth } from '../auth/AuthContext'
import { Field, TextInput } from '../components/Field'
import { useToast } from '../components/Toast'
import { describeError } from '../components/states'

export function ChangePasswordPage() {
  const { logout } = useAuth()
  const navigate = useNavigate()
  const toast = useToast()

  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState<string | null>(null)

  const change = useMutation({
    mutationFn: () => authApi.changePassword(currentPassword, newPassword),
    onSuccess: async (result) => {
      toast.success(result.message)
      // Sesi sudah dicabut di server; bersihkan juga di klien supaya tidak
      // tertinggal dalam keadaan "login" yang sebenarnya tidak berlaku lagi.
      await logout()
      navigate('/login', { replace: true })
    },
    onError: (caught) => setError(describeError(caught)),
  })

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)

    if (newPassword.length < 8) {
      setError('Password baru minimal 8 karakter.')
      return
    }
    if (newPassword !== confirmPassword) {
      setError('Konfirmasi password tidak cocok.')
      return
    }
    change.mutate()
  }

  return (
    <div className="stack">
      <div>
        <h1>Ganti password</h1>
        <div className="muted" style={{ fontSize: 12.5 }}>
          Seluruh sesi Anda akan dicabut setelah password diganti, termasuk sesi ini.
        </div>
      </div>

      <div className="card" style={{ maxWidth: 460 }}>
        <div className="card__body">
          <form className="login__form" onSubmit={handleSubmit}>
            {error && <div className="login__error">{error}</div>}

            <Field label="Password saat ini" required>
              <TextInput
                value={currentPassword}
                onChange={setCurrentPassword}
                type="password"
                autoComplete="current-password"
                disabled={change.isPending}
                maxLength={1024}
              />
            </Field>

            <Field label="Password baru" required hint="Minimal 8 karakter.">
              <TextInput
                value={newPassword}
                onChange={setNewPassword}
                type="password"
                autoComplete="new-password"
                disabled={change.isPending}
                maxLength={1024}
              />
            </Field>

            <Field
              label="Ulangi password baru"
              required
              error={
                confirmPassword && confirmPassword !== newPassword
                  ? 'Tidak cocok dengan password baru.'
                  : null
              }
            >
              <TextInput
                value={confirmPassword}
                onChange={setConfirmPassword}
                type="password"
                autoComplete="new-password"
                disabled={change.isPending}
                maxLength={1024}
              />
            </Field>

            <div className="row">
              <button
                type="submit"
                className="btn btn--primary"
                disabled={
                  change.isPending || !currentPassword || !newPassword || !confirmPassword
                }
              >
                {change.isPending ? 'Menyimpan…' : 'Ganti password'}
              </button>
              <button
                type="button"
                className="btn"
                onClick={() => {
                  setCurrentPassword('')
                  setNewPassword('')
                  setConfirmPassword('')
                  setError(null)
                }}
                disabled={change.isPending}
              >
                Bersihkan
              </button>
            </div>
          </form>
        </div>
      </div>

      <div className="card" style={{ maxWidth: 460 }}>
        <div className="card__body">
          <h2 style={{ marginBottom: 8 }}>Catatan</h2>
          <ul className="muted" style={{ margin: 0, paddingLeft: 18, fontSize: 12.5, lineHeight: 1.7 }}>
            <li>Hash memakai PBKDF2-HMAC-SHA256 dengan 600.000 iterasi.</li>
            <li>
              Bila parameter hashing dinaikkan di kemudian hari, hash lama diperbarui diam-diam
              saat login berikutnya — tidak perlu mengganti password manual.
            </li>
            <li>Password tidak pernah dikirim ulang ke browser setelah disimpan.</li>
          </ul>
        </div>
      </div>
    </div>
  )
}
