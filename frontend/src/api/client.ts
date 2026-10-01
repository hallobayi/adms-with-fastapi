/**
 * Pembungkus `fetch` untuk seluruh `/api/admin/*`.
 *
 * Tiga hal yang diurus di sini supaya tidak diulang di setiap modul endpoint:
 *
 * 1. **Cookie sesi ikut terkirim** (`credentials: 'include'`). Sesi disimpan
 *    sebagai cookie HttpOnly, jadi JavaScript tidak bisa membacanya — satu-
 *    satunya cara agar sesi terbaca adalah membiarkan browser mengirimkannya.
 * 2. **Galat FastAPI diterjemahkan menjadi `ApiError`.** `HTTPException`
 *    menghasilkan `{detail: "..."}`, sedangkan galat validasi Pydantic
 *    menghasilkan `{detail: [{loc, msg, type}]}`. Keduanya harus jadi pesan
 *    yang bisa dibaca pengguna, bukan `[object Object]`.
 * 3. **401 memicu pemberitahuan global.** Sesi bisa habis kapan saja di tengah
 *    pemakaian; tanpa pemberitahuan ini UI akan terus menampilkan halaman
 *    kosong tanpa menjelaskan kenapa.
 */

/** Akar semua endpoint admin. Sama dengan `API_PREFIX` di sisi server. */
export const API_BASE = '/api/admin'

export class ApiError extends Error {
  readonly status: number
  /** Pesan mentah dari server, sebelum dirangkai menjadi `message`. */
  readonly detail: unknown

  constructor(status: number, message: string, detail: unknown = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

/** Bentuk satu entri galat validasi Pydantic. */
interface ValidationItem {
  loc?: (string | number)[]
  msg?: string
}

/**
 * Ubah `detail` dari server menjadi satu kalimat.
 *
 * Galat validasi Pydantic menyebut lokasi field (`loc: ["body","pin"]`); itu
 * bagian yang paling berguna bagi admin, jadi ikut disertakan.
 */
function describeDetail(detail: unknown, status: number): string {
  if (typeof detail === 'string' && detail.trim()) return detail

  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => {
        const entry = item as ValidationItem
        const field = (entry.loc ?? []).filter((p) => p !== 'body').join('.')
        const msg = entry.msg ?? 'nilai tidak valid'
        return field ? `${field}: ${msg}` : msg
      })
      .filter(Boolean)
    if (parts.length) return parts.join('; ')
  }

  if (status === 401) return 'Sesi berakhir. Silakan login ulang.'
  if (status === 403) return 'Anda tidak punya wewenang untuk tindakan ini.'
  if (status === 404) return 'Data tidak ditemukan.'
  if (status === 409) return 'Bentrok dengan data yang sudah ada.'
  if (status === 422) return 'Data yang dikirim tidak valid.'
  if (status >= 500) return 'Terjadi kesalahan di server.'
  return `Permintaan gagal (HTTP ${status}).`
}

// --- Pemberitahuan 401 global --------------------------------------------

type UnauthorizedHandler = () => void

const unauthorizedHandlers = new Set<UnauthorizedHandler>()

/**
 * Daftarkan callback yang dipanggil saat server menjawab 401.
 *
 * @returns fungsi untuk membatalkan pendaftaran (dipakai `useEffect`).
 */
export function onUnauthorized(handler: UnauthorizedHandler): () => void {
  unauthorizedHandlers.add(handler)
  return () => {
    unauthorizedHandlers.delete(handler)
  }
}

function notifyUnauthorized(): void {
  for (const handler of unauthorizedHandlers) handler()
}

// --- Query string ---------------------------------------------------------

export type QueryValue = string | number | boolean | null | undefined

/**
 * Rangkai query string, lewati nilai kosong.
 *
 * Parameter kosong sengaja **dihilangkan**, bukan dikirim sebagai string
 * kosong: server membedakan "filter tidak dipakai" (`None`) dari "filter
 * bernilai kosong", dan mengirim `?status=` akan mengubah arti permintaan.
 */
export function toQuery(params?: Record<string, QueryValue>): string {
  if (!params) return ''
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue
    search.set(key, String(value))
  }
  const qs = search.toString()
  return qs ? `?${qs}` : ''
}

// --- Inti -----------------------------------------------------------------

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE'
  /** Sudah dibentuk dengan `toQuery()`; disambung apa adanya. */
  query?: Record<string, QueryValue>
  body?: unknown
  signal?: AbortSignal
}

/**
 * Kirim satu permintaan ke API dan kembalikan JSON-nya.
 *
 * `204 No Content` (dan balasan berbadan kosong) menghasilkan `undefined`,
 * sehingga pemanggil tidak perlu memeriksa status sendiri.
 */
export async function apiFetch<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const { method = 'GET', query, body, signal } = options
  const url = `${API_BASE}${path}${toQuery(query)}`

  const headers: Record<string, string> = {}
  if (body !== undefined) headers['Content-Type'] = 'application/json'

  let response: Response
  try {
    response = await fetch(url, {
      method,
      headers,
      credentials: 'include',
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    })
  } catch (error) {
    // `AbortError` bukan kegagalan — pemanggil yang membatalkannya.
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new ApiError(0, 'Tidak bisa menghubungi server. Periksa koneksi Anda.')
  }

  if (response.status === 401) notifyUnauthorized()

  if (!response.ok) {
    let detail: unknown = null
    try {
      const payload = (await response.json()) as { detail?: unknown }
      detail = payload?.detail ?? null
    } catch {
      // Balasan galat tanpa JSON (mis. HTML dari proxy) — pakai pesan umum.
    }
    throw new ApiError(response.status, describeDetail(detail, response.status), detail)
  }

  if (response.status === 204) return undefined as T

  const text = await response.text()
  if (!text) return undefined as T

  try {
    return JSON.parse(text) as T
  } catch {
    throw new ApiError(response.status, 'Balasan server tidak bisa dibaca.')
  }
}
