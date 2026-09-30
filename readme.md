# ADMS (Attendance Device Management System)

Another ADMS Server with fastAPI (Python 3.*) in universe. Project still development. If you want working project use adms php version, in below.

> http://go.topidesta.my.id/adms-php

Project very slow movement, so.. be patient.

## Struktur proyek

```
main.py                 # titik masuk: `uvicorn main:app --reload`
app/
  application.py        # application factory `create_app()`
  config.py             # pembacaan & validasi environment (settings)
  database.py           # connection pool MySQL
  schemas.py            # model request/response (Pydantic)
  store.py              # penyimpanan sementara di memori
  routers/
    health.py           # GET / dan GET /health
    items.py            # GET /items dan GET /items/{item_id}
  iclock/               # sisi DEVICE (tanpa login): protokol push ZKTeco
    router.py           #   endpoint /iclock/*
    parser.py           #   parsing payload device
    ingest.py           #   orkestrasi satu request
    store.py            #   penulisan ke MySQL
    timezones.py        #   resolusi & validasi zona waktu device
  admin/                # sisi MANUSIA (wajib login): dashboard /api/admin/*
    __init__.py         #   perakitan router & prefiks /api/admin
    security.py         #   hashing password (PBKDF2) & token sesi
    auth.py             #   tabel admin_user / admin_session
    dependencies.py     #   current_admin (401) & require_superuser (403)
    schemas.py          #   model request/response dashboard
    queries_*.py        #   kueri: devices, conflicts, attendance, master
    router_*.py         #   endpoint: auth, dashboard, devices, conflicts,
                        #             attendance, master, accounts
tests/                  # pytest + FastAPI TestClient
  run_admin_e2e.sh      # pembungkus: MySQL sementara -> migrasi -> seed -> uji
  seed_admin_e2e.sql    # data contoh yang hasilnya sudah diprediksi
  verify_admin_e2e.py   # harness verifikasi dashboard terhadap MySQL nyata
docs/                   # dokumen rancangan
  PRD-ADMS-PUSH.md      # PRD implementasi protokol push ZKTeco
  PROTOCOL-SPEC.md      # referensi teknis wire protocol (untuk parser)
  SCHEMA.md             # penjelasan skema database
migrations/             # skrip migrasi SQL
  001_init_adms_push.sql            # inti protokol push (7 tabel)
  002_biometric_sync_schedule.sql   # sidik jari, sync 2 arah, shift (6 tabel)
  003_admin_auth.sql                # akun admin & sesi login (2 tabel)
```

## Dashboard admin (`/api/admin/*`)

REST API murni (JSON) untuk kebutuhan operasional. Antarmukanya dibangun
terpisah oleh klien; server hanya menyediakan endpoint.

Seluruh endpoint kecuali `POST /api/admin/auth/login` **wajib login**. Sesi
dikirim lewat cookie `HttpOnly` + `SameSite=Lax` (`secure` mengikuti `DEBUG`),
dan token disimpan di database sebagai hash SHA-256.

| Grup | Endpoint | Kegunaan |
| --- | --- | --- |
| Autentikasi | `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`, `POST /auth/password` | masuk, keluar, identitas, ganti password sendiri |
| Ringkasan | `GET /dashboard` | lencana angka: device, konflik, kehadiran |
| Device | `GET /devices`, `GET /devices/summary`, `GET|PATCH /devices/{id}`, `POST /devices/{id}/approve` | jawab "device ini kenapa diam?" |
| Arsip request | `GET /requests`, `GET /requests/{id}` | isi mentah yang dikirim device |
| Konflik | `GET /conflicts`, `GET /conflicts/summary`, `GET /conflicts/{id}`, `POST /conflicts/{id}/resolve` | tinjau konflik sinkronisasi **secara manual** |
| Kehadiran | `GET /attendance`, `GET /attendance/summary`, `PATCH|DELETE /attendance/{id}`, `POST /attendance/recompute` | rekap harian & koreksi manual |
| Karyawan | `GET|POST /employees`, `GET|PATCH|DELETE /employees/{id}`, `GET /employees/departments` | data karyawan |
| Shift | `GET|POST /shifts`, `GET|PATCH|DELETE /shifts/{id}` | jam kerja |
| Penugasan | `GET|POST /shift-assignments`, `DELETE /shift-assignments/{id}` | siapa masuk shift apa |
| Hari libur | `GET|POST /holidays`, `DELETE /holidays/{id}` | kalender libur |
| Akun admin | `GET|POST /accounts`, `PATCH /accounts/{id}` | **khusus superuser** |

Akun admin pertama harus dibuat lewat kode (`auth.create_admin`), karena
tidak ada cara login sebelum ada akun.

### Aturan yang tidak boleh dilanggar

- **Konflik selalu ditinjau manual** (keputusan #3). Konflik tidak punya jalur
  otomatis. Baris yang kalah di-`is_valid = 0`, **tidak pernah dihapus**, supaya
  jejak audit tetap ada.
- **`daily_attendance.is_manual` dihormati** (SCHEMA §11). Koreksi admin
  menulis `is_manual = 1`, dan olah-ulang otomatis melewatinya sambil
  melaporkan berapa baris yang dilewati.
- **Punch adalah data mentah.** Mengganti PIN karyawan memutus tautan punch
  lama dan melaporkan jumlahnya; punch tidak pernah ditulis ulang diam-diam.
- **Waktu dihitung pada jam dinding lokal** (`punch_at_local`), bukan UTC —
  `shift.start_time` adalah jam setempat (SCHEMA §16).


## Rencana: ZKTeco iClock / ADMS Push Protocol

ADMS akan menerima absensi langsung dari device **ZKTeco X100C** (push), di
mana **device selalu menjadi klien** dan memanggil server kita — tidak perlu
ada port masuk ke jaringan cabang.

Keputusan yang sudah ditetapkan:

| Aspek | Keputusan |
|---|---|
| Device | ZKTeco **X100C** (fingerprint only); **firmware ADMS sudah tersedia** |
| Template biometrik | **Hanya sidik jari**, **2–4 jari per user** |
| Sinkronisasi user | **Dua arah**; konflik **selalu ditinjau manual** (tidak pernah ditimpa otomatis) |
| Sinkronisasi waktu | **TimeZone** per device (`tz_name`), diterapkan **saat parse** |
| Lokasi arsip template | **Object storage** — MySQL hanya menyimpan metadata |
| Retensi `iclock_request` | **30 hari** |
| Jadwal shift | **Ya**, untuk hitung keterlambatan |

> **Catatan:** ADMS adalah **fungsi opsional** pada X100C. Pemangku kepentingan
> sudah mengonfirmasi firmware yang dipakai mendukungnya, tetapi verifikasi
> ulang per unit baru — lihat PRD §0.3.

> **Prasyarat zona waktu:** bila memakai `CONVERT_TZ()` di MySQL, tabel zona
> waktu harus dimuat dulu, jika tidak hasilnya `NULL` (bukan error). Lihat
> SCHEMA §16.1b. Disarankan konversi tz di lapisan aplikasi (`zoneinfo`).

Baca berurutan:

1. [`docs/PRD-ADMS-PUSH.md`](docs/PRD-ADMS-PUSH.md) — tujuan, kebutuhan,
   kriteria penerimaan, tahapan
2. [`docs/PROTOCOL-SPEC.md`](docs/PROTOCOL-SPEC.md) — format wire, perintah,
   dan jebakan yang sudah terverifikasi di perangkat nyata
3. [`docs/SCHEMA.md`](docs/SCHEMA.md) — rancangan tabel + alasan tiap keputusan
   (§8b object storage, §13 konflik manual, §16 zona waktu)

Terapkan skema (13 tabel):

```bash
mysql -u <user> -p <database> < migrations/001_init_adms_push.sql
mysql -u <user> -p <database> < migrations/002_biometric_sync_schedule.sql
```

Skema sudah diverifikasi terhadap **MySQL 8.0.15** nyata: kedua migrasi jalan
bersih dan 13 tabel terbentuk.

## Menjalankan

```bash
cp env.example .env      # lalu isi kredensial MySQL
pip install -r requirements.txt
uvicorn main:app --reload
```

Dokumentasi interaktif tersedia di `/docs` bila `DEBUG=true`.

## Pengujian

```bash
pytest -v
```

Pengujian tidak memerlukan MySQL — koneksi ke database dibuat malas
(lazy), sehingga test berjalan di mesin bersih.

### Verifikasi terhadap MySQL nyata

Suite di atas tidak menyentuh database, jadi ia tidak bisa membuktikan hal-hal
seperti `ON DUPLICATE KEY`, FK `RESTRICT`, atau apakah `SUM(...)` benar-benar
mengembalikan angka yang diharapkan. Untuk itu ada
`tests/verify_admin_e2e.py`: harness yang menjalankan seluruh alur dashboard
lewat HTTP (92 pemeriksaan) terhadap instance MySQL sementara, lengkap dengan
data contoh yang sudah diatur agar hasilnya bisa diprediksi.

```bash
bash tests/run_admin_e2e.sh
```

Skrip itu menyalakan instance sementara di port terpisah dengan
`--no-defaults` (**tidak menyentuh MySQL milik Anda** di 3306), menjalankan
`migrations/001..003`, memuat `tests/seed_admin_e2e.sql`, menjalankan harness,
lalu mematikan dan menghapus instance tersebut. Kode keluar 0 berarti lulus.

Harness ini pernah **menemukan tiga bug nyata** yang tidak terlihat oleh unit
test:

| Bug | Gejala |
| --- | --- |
| `AS leave` (kata kunci MySQL) | `GET /attendance` gagal 500 dengan galat sintaks 1064 |
| Perhitungan telat memakai jam **UTC** | telat 30 menit terbaca **1000 menit**, dan karyawan tepat waktu ikut berstatus `late` |
| Kolom `SET` dikembalikan sebagai `set` Python | `work_days` keluar sebagai `"{'MO', 'TU'}"` di JSON |

Ketiganya sekarang dijaga oleh `tests/test_admin_attendance_logic.py`.

## Konfigurasi

Semua konfigurasi dibaca dari environment variable dan divalidasi sekali
saat aplikasi start (lihat `app/config.py`). Variabel `MYSQL_HOST`,
`MYSQL_USER`, `MYSQL_PASSWORD`, dan `MYSQL_DB` bersifat wajib; bila salah
satu kosong aplikasi berhenti dengan pesan yang jelas alih-alih gagal
jauh di dalam kueri.

# Authors

- [@mdestafadilah](https://github.com/mdestafadilah)
