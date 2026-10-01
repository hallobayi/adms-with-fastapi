/**
 * Kelola akun admin — hanya untuk superuser.
 *
 * Dua aturan yang datang dari server dan **ditampilkan lebih dulu** di sini,
 * bukan dibiarkan admin menemukannya lewat galat:
 *
 * - Superuser tidak bisa menurunkan wewenang atau menonaktifkan **akunnya
 *   sendiri**. Tanpa aturan itu, satu salah klik bisa membuat sistem tidak
 *   punya superuser lagi — dan tidak ada jalan masuk untuk memperbaikinya
 *   selain mengubah database manual.
 * - Mengganti password akun selalu **mencabut seluruh sesi** akun itu, supaya
 *   pemakai token yang sudah bocor benar-benar terlempar keluar.
 */

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { accountsApi } from '../api/endpoints'
import type { AccountOut } from '../api/types'
import { useCurrentAdmin } from '../auth/AuthContext'
import { DataTable, type Column } from '../components/DataTable'
import { Checkbox, Field, TextInput } from '../components/Field'
import { Modal } from '../components/Modal'
import { Badge } from '../components/StatusBadge'
import { useToast } from '../components/Toast'
import { QueryState, describeError } from '../components/states'
import { formatDateTime, orDash } from '../lib/format'

export function AccountsPage() {
  const queryClient = useQueryClient()
  const toast = useToast()
  const me = useCurrentAdmin()

  const [creating, setCreating] = useState(false)
  const [editing, setEditing] = useState<AccountOut | null>(null)

  const query = useQuery({
    queryKey: ['accounts'],
    queryFn: () => accountsApi.list(),
  })

  function refresh() {
    void queryClient.invalidateQueries({ queryKey: ['accounts'] })
  }

  const columns: Column<AccountOut>[] = [
    {
      key: 'username',
      header: 'Username',
      render: (row) => (
        <>
          <div className="mono">{row.username}</div>
          <div className="muted" style={{ fontSize: 11.5 }}>{orDash(row.display_name)}</div>
        </>
      ),
    },
    {
      key: 'role',
      header: 'Wewenang',
      render: (row) => (
        <div className="row" style={{ gap: 5, flexWrap: 'nowrap' }}>
          {row.is_superuser ? <Badge tone="primary">Superuser</Badge> : <Badge tone="neutral">Admin</Badge>}
          {row.id === me.id && <Badge tone="info">Anda</Badge>}
        </div>
      ),
    },
    {
      key: 'active',
      header: 'Status',
      render: (row) =>
        row.is_active ? <Badge tone="ok">Aktif</Badge> : <Badge tone="danger">Nonaktif</Badge>,
    },
    {
      key: 'last_login',
      header: 'Terakhir masuk',
      render: (row) => formatDateTime(row.last_login_at),
    },
    {
      key: 'created',
      header: 'Dibuat',
      render: (row) => formatDateTime(row.created_at),
    },
  ]

  return (
    <div className="stack">
      <div className="row row--between">
        <div>
          <h1>Akun admin</h1>
          <div className="muted" style={{ fontSize: 12.5 }}>
            Mengganti password sebuah akun mencabut seluruh sesi akun itu.
          </div>
        </div>
        <button type="button" className="btn btn--primary btn--sm" onClick={() => setCreating(true)}>
          Tambah akun
        </button>
      </div>

      <div className="card">
        <QueryState
          isPending={query.isPending}
          error={query.error}
          isEmpty={query.data?.accounts.length === 0}
          emptyTitle="Belum ada akun"
          loadingLabel="Memuat akun…"
          onRetry={() => void query.refetch()}
        >
          <DataTable
            rows={query.data?.accounts ?? []}
            columns={columns}
            rowKey={(row) => row.id}
            actions={(row) => (
              <button type="button" className="btn btn--sm" onClick={() => setEditing(row)}>
                Ubah
              </button>
            )}
          />
        </QueryState>
      </div>

      {creating && (
        <AccountCreateModal
          onClose={() => setCreating(false)}
          onSaved={(message) => {
            toast.success(message)
            setCreating(false)
            refresh()
          }}
        />
      )}

      {editing && (
        <AccountEditModal
          account={editing}
          isSelf={editing.id === me.id}
          onClose={() => setEditing(null)}
          onSaved={(message) => {
            toast.success(message)
            setEditing(null)
            refresh()
          }}
        />
      )}
    </div>
  )
}

// --- Tambah akun ----------------------------------------------------------

function AccountCreateModal({
  onClose,
  onSaved,
}: {
  onClose: () => void
  onSaved: (message: string) => void
}) {
  const toast = useToast()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [isSuperuser, setIsSuperuser] = useState(false)

  const usernameValid = /^[A-Za-z0-9._-]{3,64}$/.test(username)
  const passwordValid = password.length >= 8

  const save = useMutation({
    mutationFn: () =>
      accountsApi.create({
        username: username.trim(),
        password,
        display_name: displayName.trim() || null,
        is_superuser: isSuperuser,
      }),
    onSuccess: (result) => onSaved(result.message),
    onError: (error) => toast.error(describeError(error)),
  })

  return (
    <Modal
      title="Tambah akun admin"
      onClose={onClose}
      busy={save.isPending}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose} disabled={save.isPending}>
            Batal
          </button>
          <button
            type="button"
            className="btn btn--primary"
            onClick={() => save.mutate()}
            disabled={save.isPending || !usernameValid || !passwordValid}
          >
            {save.isPending ? 'Menyimpan…' : 'Buat akun'}
          </button>
        </>
      }
    >
      <div className="stack">
        <Field
          label="Username"
          required
          error={
            username && !usernameValid
              ? '3–64 karakter; hanya huruf, angka, titik, garis bawah, dan tanda hubung.'
              : null
          }
        >
          <TextInput
            value={username}
            onChange={setUsername}
            mono
            maxLength={64}
            autoComplete="off"
          />
        </Field>

        <Field
          label="Password"
          required
          error={password && !passwordValid ? 'Minimal 8 karakter.' : null}
          hint="Disimpan sebagai PBKDF2-HMAC-SHA256 (600.000 iterasi)."
        >
          <TextInput
            value={password}
            onChange={setPassword}
            type="password"
            maxLength={1024}
            autoComplete="new-password"
          />
        </Field>

        <Field label="Nama tampilan">
          <TextInput value={displayName} onChange={setDisplayName} maxLength={128} />
        </Field>

        <Checkbox
          checked={isSuperuser}
          onChange={setIsSuperuser}
          label="Jadikan superuser (bisa mengelola akun lain)"
        />
      </div>
    </Modal>
  )
}

// --- Ubah akun ------------------------------------------------------------

function AccountEditModal({
  account,
  isSelf,
  onClose,
  onSaved,
}: {
  account: AccountOut
  isSelf: boolean
  onClose: () => void
  onSaved: (message: string) => void
}) {
  const toast = useToast()
  const [displayName, setDisplayName] = useState(account.display_name ?? '')
  const [isActive, setIsActive] = useState(account.is_active)
  const [isSuperuser, setIsSuperuser] = useState(account.is_superuser)
  const [password, setPassword] = useState('')

  const passwordValid = password.length === 0 || password.length >= 8

  const save = useMutation({
    mutationFn: () =>
      accountsApi.update(account.id, {
        display_name: displayName.trim() || null,
        is_active: isActive,
        is_superuser: isSuperuser,
        ...(password ? { password } : {}),
      }),
    onSuccess: (result) => onSaved(result.message),
    onError: (error) => toast.error(describeError(error)),
  })

  const selfDemotion = isSelf && (!isSuperuser || !isActive)

  return (
    <Modal
      title={`Ubah akun ${account.username}`}
      onClose={onClose}
      busy={save.isPending}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose} disabled={save.isPending}>
            Batal
          </button>
          <button
            type="button"
            className="btn btn--primary"
            onClick={() => save.mutate()}
            disabled={save.isPending || !passwordValid || selfDemotion}
            title={selfDemotion ? 'Tidak bisa menurunkan wewenang akun sendiri' : undefined}
          >
            {save.isPending ? 'Menyimpan…' : 'Simpan'}
          </button>
        </>
      }
    >
      <div className="stack">
        {isSelf && (
          <div
            className="login__error"
            style={{ background: 'var(--info-soft)', color: 'var(--info)' }}
          >
            Ini akun Anda sendiri. Wewenang superuser dan status aktif tidak bisa diturunkan
            dari sini — itu aturan server, supaya sistem tidak pernah kehabisan superuser.
          </div>
        )}

        <Field label="Nama tampilan">
          <TextInput value={displayName} onChange={setDisplayName} maxLength={128} />
        </Field>

        <Field
          label="Password baru"
          hint="Kosongkan bila tidak diganti. Mengisi ini akan mencabut seluruh sesi akun tersebut."
          error={!passwordValid ? 'Minimal 8 karakter.' : null}
        >
          <TextInput
            value={password}
            onChange={setPassword}
            type="password"
            maxLength={1024}
            autoComplete="new-password"
          />
        </Field>

        <Checkbox
          checked={isActive}
          onChange={setIsActive}
          disabled={isSelf}
          label="Akun aktif"
        />

        <Checkbox
          checked={isSuperuser}
          onChange={setIsSuperuser}
          disabled={isSelf}
          label="Superuser"
        />
      </div>
    </Modal>
  )
}
