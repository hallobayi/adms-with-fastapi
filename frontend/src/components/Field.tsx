/**
 * Primitif formulir.
 *
 * Tujuannya bukan membungkus `<input>` tanpa alasan, melainkan memastikan dua
 * hal selalu berpasangan: label dengan kontrolnya, dan pesan galat dengan
 * field yang salah. Formulir di sini mengisi data karyawan, PIN, dan jam shift
 * — kesalahan isi di situ berdampak langsung ke perhitungan kehadiran, jadi
 * setiap field harus bisa ditunjuk dengan jelas.
 */

import type { ChangeEvent, ReactNode } from 'react'

interface FieldProps {
  label: string
  /** Ditampilkan sebagai keterangan kecil di bawah kontrol. */
  hint?: ReactNode
  /** Bila diisi, ditampilkan merah dan menandai field ini bermasalah. */
  error?: string | null
  required?: boolean
  children: ReactNode
}

export function Field({ label, hint, error, required, children }: FieldProps) {
  return (
    <label className="field">
      <span className="field__label">
        {label}
        {required && <span> *</span>}
      </span>
      {children}
      {error ? <span className="field__error">{error}</span> : hint ? <span className="field__hint">{hint}</span> : null}
    </label>
  )
}

// --- Kontrol dasar --------------------------------------------------------

interface TextInputProps {
  value: string
  onChange: (value: string) => void
  type?: 'text' | 'password' | 'email' | 'tel' | 'date' | 'time' | 'datetime-local'
  placeholder?: string
  disabled?: boolean
  /** Pakai font monospace — untuk PIN, serial number, dan body mentah. */
  mono?: boolean
  autoFocus?: boolean
  autoComplete?: string
  maxLength?: number
}

export function TextInput({
  value,
  onChange,
  type = 'text',
  placeholder,
  disabled,
  mono,
  autoFocus,
  autoComplete,
  maxLength,
}: TextInputProps) {
  return (
    <input
      className={mono ? 'input input--mono' : 'input'}
      type={type}
      value={value}
      placeholder={placeholder}
      disabled={disabled}
      autoFocus={autoFocus}
      autoComplete={autoComplete}
      maxLength={maxLength}
      onChange={(event: ChangeEvent<HTMLInputElement>) => onChange(event.target.value)}
    />
  )
}

interface NumberInputProps {
  value: string
  onChange: (value: string) => void
  min?: number
  max?: number
  placeholder?: string
  disabled?: boolean
}

/**
 * Masukan angka yang **tetap menyimpan string**.
 *
 * Kalau nilainya disimpan sebagai `number`, kotak akan melompat ke `0` saat
 * pengguna menghapus isinya untuk mengetik angka baru — perilaku yang membuat
 * `late_tolerance_min` sering tidak sengaja bernilai 0. Konversi ke angka
 * dilakukan sekali saja saat dikirim ke server.
 */
export function NumberInput({ value, onChange, min, max, placeholder, disabled }: NumberInputProps) {
  return (
    <input
      className="input"
      type="number"
      inputMode="numeric"
      value={value}
      min={min}
      max={max}
      placeholder={placeholder}
      disabled={disabled}
      onChange={(event: ChangeEvent<HTMLInputElement>) => onChange(event.target.value)}
    />
  )
}

interface SelectOption {
  value: string
  label: string
}

interface SelectProps {
  value: string
  onChange: (value: string) => void
  options: SelectOption[]
  disabled?: boolean
  /** Label untuk pilihan kosong; bila diisi, `<option value="">` ikut dibuat. */
  placeholder?: string
}

export function Select({ value, onChange, options, disabled, placeholder }: SelectProps) {
  return (
    <select
      className="select"
      value={value}
      disabled={disabled}
      onChange={(event: ChangeEvent<HTMLSelectElement>) => onChange(event.target.value)}
    >
      {placeholder !== undefined && <option value="">{placeholder}</option>}
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  )
}

interface CheckboxProps {
  checked: boolean
  onChange: (checked: boolean) => void
  label: ReactNode
  disabled?: boolean
}

export function Checkbox({ checked, onChange, label, disabled }: CheckboxProps) {
  return (
    <label className="checkbox">
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(event: ChangeEvent<HTMLInputElement>) => onChange(event.target.checked)}
      />
      <span>{label}</span>
    </label>
  )
}

interface TextareaProps {
  value: string
  onChange: (value: string) => void
  rows?: number
  placeholder?: string
  disabled?: boolean
  maxLength?: number
}

export function Textarea({ value, onChange, rows = 3, placeholder, disabled, maxLength }: TextareaProps) {
  return (
    <textarea
      className="textarea"
      value={value}
      rows={rows}
      placeholder={placeholder}
      disabled={disabled}
      maxLength={maxLength}
      onChange={(event: ChangeEvent<HTMLTextAreaElement>) => onChange(event.target.value)}
    />
  )
}
