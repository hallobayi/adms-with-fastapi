/**
 * Pemformat tampilan.
 *
 * Waktu dari server berupa **string** yang sudah diformat server
 * (`schemas._iso`, mis. `"2026-10-01 10:29:00"`) dan tanpa penanda zona.
 * Karena itu fungsi di sini **tidak** memakai `new Date(...)` untuk
 * memformat ulang: `new Date("2026-10-01 10:29:00")` ditafsirkan sebagai
 * waktu lokal browser, sehingga jam yang sudah benar bisa bergeser hanya
 * karena mesin admin berada di zona lain. Yang dilakukan adalah mengurai
 * string itu apa adanya lalu menatanya kembali.
 */

const MONTHS_SHORT = [
  'Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun',
  'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des',
]

const MONTHS_LONG = [
  'Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni',
  'Juli', 'Agustus', 'September', 'Oktober', 'November', 'Desember',
]

/** Pisahkan `"2026-10-01 10:29:00"` / `"2026-10-01T10:29:00"` tanpa konversi zona. */
function splitStamp(value: string): { date: string; time: string } {
  const [datePart = '', timePart = ''] = value.trim().split(/[T ]/)
  return { date: datePart, time: timePart }
}

/** `"2026-10-01"` → `"01 Okt 2026"`. Nilai tak dikenal dikembalikan apa adanya. */
export function formatDate(value: string | null | undefined): string {
  if (!value) return '—'
  const { date } = splitStamp(value)
  const [year, month, day] = date.split('-')
  if (!year || !month || !day) return value
  const monthName = MONTHS_SHORT[Number(month) - 1]
  if (!monthName) return value
  return `${day} ${monthName} ${year}`
}

/** `"2026-10-01"` → `"1 Oktober 2026"` (untuk judul, bukan tabel). */
export function formatDateLong(value: string | null | undefined): string {
  if (!value) return '—'
  const { date } = splitStamp(value)
  const [year, month, day] = date.split('-')
  if (!year || !month || !day) return value
  const monthName = MONTHS_LONG[Number(month) - 1]
  if (!monthName) return value
  return `${Number(day)} ${monthName} ${year}`
}

/** `"2026-10-01 10:29:00"` → `"01 Okt 2026, 10:29"`. */
export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—'
  const { date, time } = splitStamp(value)
  const day = formatDate(date)
  if (!time) return day
  return `${day}, ${time.slice(0, 5)}`
}

/** Jam saja: `"2026-10-01 10:29:00"` → `"10:29"`. */
export function formatTime(value: string | null | undefined): string {
  if (!value) return '—'
  const { time } = splitStamp(value)
  return time ? time.slice(0, 5) : '—'
}

/**
 * Ubah menit menjadi durasi ringkas: `450` → `"7j 30m"`.
 *
 * Dipakai untuk `late_minutes`, `overtime_minutes`, dan seterusnya. Nilai 0
 * tetap ditampilkan sebagai `"0m"` supaya kolom tabel tidak berlubang.
 */
export function formatMinutes(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined) return '—'
  const total = Math.max(0, Math.round(minutes))
  const hours = Math.floor(total / 60)
  const rest = total % 60
  if (!hours) return `${rest}m`
  if (!rest) return `${hours}j`
  return `${hours}j ${rest}m`
}

/** Ukuran berkas ringkas: `1536` → `"1,5 KB"`. */
export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return '—'
  if (bytes < 1024) return `${bytes} B`
  const kb = bytes / 1024
  if (kb < 1024) return `${kb.toFixed(kb < 10 ? 1 : 0)} KB`
  return `${(kb / 1024).toFixed(1)} MB`
}

/**
 * Selisih waktu dari sekarang dalam bahasa Indonesia.
 *
 * Di sini `new Date()` memang dipakai — tetapi hanya untuk **membandingkan
 * jarak**, bukan untuk menampilkan jam. Selisihnya dibulatkan kasar supaya
 * tidak menyesatkan (device yang terakhir terlihat 3 menit lalu tidak perlu
 * ditampilkan sebagai "2 menit 47 detik lalu").
 */
export function relativeTime(value: string | null | undefined): string {
  if (!value) return 'belum pernah'

  const normalized = value.trim().replace(' ', 'T')
  const then = new Date(normalized)
  if (Number.isNaN(then.getTime())) return value

  const seconds = Math.round((Date.now() - then.getTime()) / 1000)
  if (seconds < 0) return 'baru saja'
  if (seconds < 60) return 'baru saja'

  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes} menit lalu`

  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} jam lalu`

  const days = Math.floor(hours / 24)
  if (days < 30) return `${days} hari lalu`

  const months = Math.floor(days / 30)
  if (months < 12) return `${months} bulan lalu`

  return `${Math.floor(months / 12)} tahun lalu`
}

/** Tampilkan nilai apa pun sebagai teks; `null`/kosong menjadi `"—"`. */
export function orDash(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  const text = String(value).trim()
  return text === '' ? '—' : text
}

/** Tanggal hari ini sebagai `"YYYY-MM-DD"`, memakai jam lokal browser. */
export function todayISO(): string {
  const now = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
}

/** Geser tanggal ISO sebanyak `days` hari (boleh negatif). */
export function shiftISO(iso: string, days: number): string {
  const [year, month, day] = iso.split('-').map(Number)
  if (!year || !month || !day) return iso
  const base = new Date(year, month - 1, day)
  base.setDate(base.getDate() + days)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${base.getFullYear()}-${pad(base.getMonth() + 1)}-${pad(base.getDate())}`
}

/** Nama hari Indonesia untuk tanggal ISO. */
export function weekdayName(iso: string): string {
  const [year, month, day] = iso.split('-').map(Number)
  if (!year || !month || !day) return ''
  const names = ['Minggu', 'Senin', 'Selasa', 'Rabu', 'Kamis', 'Jumat', 'Sabtu']
  return names[new Date(year, month - 1, day).getDay()] ?? ''
}
