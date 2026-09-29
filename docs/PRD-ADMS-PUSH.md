# PRD — Implementasi ZKTeco iClock / ADMS Push Protocol

**Proyek:** ADMS (Attendance Device Management System)
**Versi dokumen:** 2.0
**Tanggal:** 2026-09-29
**Status:** Siap implementasi — keputusan terbuka sudah dijawab
**Stack:** FastAPI + MySQL 8 (`app/` yang sudah direfactor)

---

## 0. Keputusan yang sudah ditetapkan

| # | Pertanyaan | Keputusan | Dampak |
|---|---|---|---|
| 1 | Model device | **ZKTeco X100C** | Fingerprint saja; varian ATTLOG yang diuji dibatasi ke yang didukung X100C |
| 2 | Template biometrik | **HANYA sidik jari** | Tambah `finger_template` (BLOB). Tabel face/photo **tidak** dibuat. |
| 3 | Sinkronisasi user | **DUA ARAH** | Perlu `version` + `sync_state`, tabel `sync_log`, dan aturan konflik eksplisit |
| 4 | Retensi `iclock_request` | **30 hari** | Job pembersihan + pemadatan `body_raw` bertahap |
| 5 | Hubungkan ke shift | **YA** | Tambah `shift`, `shift_assignment`, `daily_attendance`, `holiday` |

**Konsekuensi penting dari keputusan #3:** sinkronisasi dua arah sidik jari
adalah bagian paling berisiko di proyek ini. Template sidik jari tidak bisa
"diperbaiki" — bila salah menimpa, karyawan harus datang dan merekam ulang.
Lihat §6 FR-7 dan §5 NFR-6.

Dokumen terkait: `docs/PROTOCOL-SPEC.md` (wire format),
`docs/SCHEMA.md` (desain tabel), `migrations/` (skrip SQL).

---

## 0.1 Peringatan awal — ADMS adalah fitur OPSIONAL di X100C

Dari lembar spesifikasi X100C, **ADMS dan Webserver tercantum sebagai
"Optional Functions"**, berbeda dari SMS/Workcode/DST/Scheduled-bell yang
standar. Ini berarti device yang dibeli belum tentu bisa memakai mode push.

> **Tindakan sebelum fase F1:** pastikan firmware X100C yang ada sudah
> mendukung PUSH/ADMS. Bila belum, device perlu upgrade firmware via USB.
> **Seluruh pekerjaan integrasi tidak bisa diuji tanpa ini.**

Ini bukan detail administratif — ini penentu apakah proyek bisa berjalan.
Sebaiknya diverifikasi dengan satu device contoh sebelum menulis banyak kode.

---

## 1. Ringkasan

ADMS perlu menerima data absensi dari perangkat biometrik ZKTeco secara
langsung, tanpa penarikan (pull) dari sisi server. Perangkat ZKTeco mendukung
mode **Push SDK / ADMS**, di mana **perangkat yang selalu menjadi klien** dan
menginisiasi seluruh koneksi HTTP ke server kita. Server hanya menyediakan
endpoint dan membalas teks biasa.

Fitur ini menggantikan pola lama (menyambung ke device via TCP/SDK) dengan
arsitektur yang lebih sederhana: tidak ada port masuk ke jaringan lokal cabang,
cukup device bisa menjangkau URL server.

### 1.1 Tujuan

| # | Tujuan | Ukuran keberhasilan |
|---|---|---|
| G1 | Menerima absensi real-time dari device | Punch muncul di DB < 5 detik setelah scan |
| G2 | Tahan terhadap jaringan putus | Device re-push otomatis; tidak ada data hilang |
| G3 | Tidak ada duplikat walau device kirim ulang | 1 punch = 1 baris di `attendance_log` |
| G4 | Server dapat mengirim perintah ke device | Tambah/hapus user sampai di device < 1 siklus poll |
| G5 | Data mentah tersimpan untuk audit | Body mentah tiap request tersimpan utuh |
| G6 | Sidik jari tersinkron dua arah | User yang didaftarkan di satu device bisa verifikasi di device lain |
| G7 | Keterlambatan dihitung otomatis | `daily_attendance` terisi tanpa intervensi manual |

### 1.2 Non-tujuan (di luar cakupan)

- **Template wajah / face recognition** — keputusan: HANYA sidik jari. X100C
  memang device fingerprint.
- **Penarikan foto absensi** (ATTPHOTO / BIOPHOTO) — device tidak memilikinya.
- Manajemen akses pintu (door control), alarm, dan interlock.
- Aplikasi web UI penuh untuk manajemen karyawan (hanya API + halaman monitor sederhana).
- Penggajian (payroll). Sistem ini menghasilkan data kehadiran, bukan slip gaji.

---

## 2. Latar belakang protokol

Bagian ini merangkum hasil riset dari implementasi nyata yang sudah
diverifikasi di perangkat keras. Detail teknis lengkap ada di
`docs/PROTOCOL-SPEC.md`.

### 2.1 Alur komunikasi

```
Device                                  Server (FastAPI)
  │                                          │
  │── GET /iclock/cdata?SN=XXX ─────────────►│ 1. Handshake, device minta konfigurasi
  │◄── "GET OPTION FROM: XXX\r\n..." ────────│
  │                                          │
  │── POST /iclock/cdata?SN&table=ATTLOG ───►│ 2. Push absensi
  │◄── "OK: 12" ─────────────────────────────│
  │                                          │
  │── GET /iclock/getrequest?SN=XXX ────────►│ 3. Poll perintah tiap `Delay` detik
  │◄── "C:15:DATA QUERY USERINFO" ───────────│
  │                                          │
  │── POST /iclock/cdata?table=USERINFO ────►│ 4. Data hasil query dikirim balik
  │◄── "OK: 3" ──────────────────────────────│
  │                                          │
  │── POST /iclock/devicecmd ───────────────►│ 5. Laporan hasil eksekusi perintah
  │◄── "OK" ─────────────────────────────────│
```

**Prinsip penting:** device tidak pernah menerima perintah pada respons
`/iclock/cdata`. Semua perintah ke device **hanya** dikirim sebagai balasan
`/iclock/getrequest`. Ini memisahkan jalur data-masuk dan jalur perintah.

### 2.2 Empat endpoint yang wajib ada

| Endpoint | Method | Fungsi |
|---|---|---|
| `/iclock/cdata` | GET | Handshake + minta konfigurasi |
| `/iclock/cdata` | POST | Kirim data (ATTLOG, OPERLOG, USERINFO, OPTIONS) |
| `/iclock/getrequest` | GET | Device poll perintah dari server |
| `/iclock/devicecmd` | POST | Device lapor hasil eksekusi perintah |
| `/iclock/ping` | GET | Heartbeat ringan (opsional, sebagian firmware) |
| `/iclock/registry` | GET/POST | Registrasi + kapabilitas device (opsional) |

### 2.3 Parameter konfigurasi handshake

Server membalas handshake dengan blok teks `key=value` berakhiran `\r\n`
(**wajib CRLF**, bukan hanya LF):

```
GET OPTION FROM: <SN>
Stamp=9999
OpStamp=<unix_timestamp>
ErrorDelay=60
Delay=30
ResLogDay=18250
ResLogDelCount=10000
ResLogCount=50000
TransTimes=00:00;14:05
TransInterval=1
TransFlag=1111000000
Realtime=1
Encrypt=0
```

**Catatan penting yang sering jadi sumber bug:**

- `TransFlag` menentukan tabel mana yang dikirim. Menyetelnya salah membuat
  device **sama sekali tidak mengirim** data tertentu.
- `TimeZone` **sengaja tidak dikirim** secara default. Bila dikirim, device
  akan menggeser jamnya dan bisa merusak timestamp absensi yang sudah ada.
  Sediakan flag konfigurasi (`ZKTECO_SYNC_TIMEZONE`, default `false`).
- `Realtime=1` membuat punch dikirim segera, bukan menunggu jadwal `TransTimes`.

### 2.4 Format record ATTLOG

Ada **tiga varian** format yang beredar di lapangan. Parser **wajib** menangani
ketiganya, karena varian bergantung pada model dan firmware:

**Varian A — posisional, tab-separated (paling umum):**
```
1001	2026-09-29 08:30:00	0	1	0
```
Urutan: `PIN`, `DateTime`, `Status`, `Verify`, `WorkCode`

**Varian B — posisional dengan field tambahan (beberapa firmware):**
```
1001	2026-09-29 08:30:00	0	0	0	0
```
7–11 kolom, kolom ke-3 dst adalah reserved/status tambahan.

**Varian C — `key=value`:**
```
PIN=1001	DateTime=2026-09-29 08:30:00	Verified=1	Status=0
```

Timestamp bisa berupa `YYYY-MM-DD HH:MM:SS` **atau** Unix epoch detik.

**Kode Status:** `0`=Check In, `1`=Check Out, `2`=Break Out, `3`=Break In,
`4`=Overtime In, `5`=Overtime Out
**Kode Verify:** `0/3`=Password, `1/5`=Fingerprint, `2/4`=Card, `15`=Face, `25`=Palm

### 2.5 Format perintah (dari `getrequest`)

```
C:<ID>:<CMD>\r\n
```

`<ID>` = bilangan bulat naik monoton, dialokasikan server saat perintah
di-antrikan. ID ini yang dipakai untuk mencocokkan laporan di `devicecmd`.

Perintah yang **terverifikasi** di perangkat keras (firmware ZAM180-NF):

| Perintah | CMD echo | Keterangan |
|---|---|---|
| `INFO` | `INFO` | Ambil info lengkap device |
| `CHECK` | `CHECK` | Heartbeat |
| `GET OPTION FROM <key>` | `GET OPTION` | Ambil satu nilai konfigurasi |
| `DATA UPDATE USERINFO PIN=<p>\tName=<n>\tPrivilege=<v>\tCard=<c>` | `DATA` | Tambah/ubah user |
| `DATA DELETE USERINFO PIN=<p>` | `DATA` | Hapus user |
| `DATA QUERY USERINFO` | `DATA` | Minta seluruh user |
| `Shell <cmd>` | `Shell` | Jalankan perintah OS di device |

### 2.6 Jebakan yang wajib dihindari

Ini temuan dari pengujian di perangkat nyata — bukan teori:

1. **`USER ADD` / `USER DEL` DITOLAK dengan `-1002`.** Datasheet ZKTeco
   mencantumkan `USER ADD`, tetapi firmware nyata menolaknya sebagai sintaks
   tidak valid. **Gunakan `DATA UPDATE USERINFO` / `DATA DELETE USERINFO`.**
2. **`DATA DEL` (singkatan) juga gagal.** Harus kata penuh `DELETE`.
3. **`DATA QUERY` tidak mengembalikan data di respons perintah.** Data dikirim
   terpisah lewat `POST /iclock/cdata?table=USERINFO`.
4. **Field perintah dipisah TAB**, bukan spasi. Spasi merusak nama yang
   mengandung spasi (`Bob Marley`).
5. **Nama user bisa mengandung karakter khusus.** Newline/CR dalam nilai field
   memungkinkan **command injection** ke wire protocol. Wajib divalidasi.
6. **Response `/iclock/cdata` harus `text/plain`.** Device tidak mem-parse JSON.

### 2.7 Kode balikan perintah (dari `devicecmd`)

| Kode | Arti |
|---|---|
| `0` | Sukses |
| `-1` | Perintah tidak didukung / tidak ada data |
| `-2` | Operasi file gagal |
| `-1002` | Sintaks perintah tidak valid |
| `-1004` | Tabel/fitur tidak didukung model ini |

Kode `-1004` penting: artinya kita **tidak boleh** terus mengirim perintah yang
sama ke model tersebut. Scheduler perlu menandai kapabilitas per device.

---

## 3. Arsitektur yang diusulkan

```
app/
  iclock/                          # modul baru, terisolasi dari API internal
    __init__.py
    router.py                      # 4+ endpoint /iclock/*
    protocol.py                    # builder respons, format CRLF, C:ID:CMD
    parser.py                      # parser ATTLOG/OPERLOG/USERINFO (3 varian)
    commands.py                    # kosakata perintah + validasi anti-injection
    service.py                     # orkestrasi: ingest, antrian perintah, dedup
    deps.py                        # dependency auth device
  biometric/
    fingerprint.py                 # (de)serialisasi blob template sidik jari
    sync.py                        # mesin sinkronisasi dua arah + resolusi konflik
  attendance/
    calculate.py                   # hitung keterlambatan dari shift
    schedule.py                    # resolusi shift yang berlaku per tanggal
  models/                          # model SQLAlchemy / skema MySQL
  routers/
    devices.py                     # API internal: kelola device (auth JWT)
    attendance.py                  # API internal: baca absensi
    commands.py                    # API internal: antrikan perintah ke device
    shifts.py                      # API internal: kelola shift & penugasan
  jobs/
    compute_daily.py               # job: attendance_log -> daily_attendance
    retention.py                   # job: retensi iclock_request 30 hari
    device_health.py               # job: pantau online + AttLogCount
```

**Alasan pemisahan `app/iclock/`:** endpoint ini tidak memakai auth pengguna
dan formatnya non-JSON. Mengisolasi ke modul sendiri mencegah logika wire
protocol bocor ke lapisan API internal yang memakai JSON + JWT.

### 3.1 Keputusan desain kunci

| Keputusan | Pilihan | Alasan |
|---|---|---|
| Penyimpanan data mentah | **Selalu simpan body mentah** | Saat parser salah tafsir, data asli masih bisa diproses ulang |
| Idempotensi | **UNIQUE constraint pada hash punch** | Device memang mengirim ulang saat jaringan putus; constraint mencegah duplikat |
| Sumber waktu | **Timestamp device**, bukan waktu server | Punch offline harus tetap tercatat di waktu kejadian |
| Autentikasi device | **Token per device di URL `push`** | Firmware hanya mendukung URL statis; lihat §5 |
| Perintah ke device | **Antrian di DB**, bukan di memori | Server bisa restart tanpa kehilangan perintah |
| Balasan sukses | `OK: <jumlah>` | Kompatibel dengan banyak firmware & memberi umpan balik jumlah |

### 3.2 Model idempotensi (krusial)

Device akan mengirim ulang data yang sama bila tidak menerima `OK` — dan ini
normal terjadi. Namun **`Stamp` dari device tidak dapat dipercaya sebagai
penanda unik** karena perilakunya berbeda antar firmware.

Solusi: hitung **fingerprint deterministik** dari isi punch dan pasang
`UNIQUE` index. Rujuk §4 tabel `attendance_log` kolom `record_hash`.

```
record_hash = SHA1(device_id | pin | punch_at | status | verify_mode | work_code)
```

Dengan `INSERT ... ON DUPLICATE KEY UPDATE` atau `INSERT IGNORE`, pengiriman
ulang menjadi tidak berbahaya.

---

## 4. Kebutuhan fungsional

### FR-1 Handshake & registrasi device
- **FR-1.1** `GET /iclock/cdata?SN=<sn>` membalas blok konfigurasi CRLF.
- **FR-1.2** Device yang belum dikenal **tetap dibalas**, dan dicatat sebagai
  `unregistered`. Tidak boleh membalas error, karena device akan berhenti
  mencoba. Munculkan di daftar "device menunggu persetujuan".
- **FR-1.3** `GET /iclock/cdata?SN=<sn>&options=all` juga membalas blok yang sama.
- **FR-1.4** `POST /iclock/cdata?SN=<sn>&table=options&c=registry` mencatat
  kapabilitas device (parsing `key=value` dipisah koma; key boleh berawalan `~`
  yang harus dilepas) dan membalas `OK`.

### FR-2 Ingest absensi
- **FR-2.1** Terima `POST /iclock/cdata?SN=<sn>&table=ATTLOG`.
- **FR-2.2** Parser mendukung 3 varian format (§2.4) secara otomatis.
- **FR-2.3** Simpan **setiap baris** ke `attendance_log`, termasuk yang gagal
  ditafsirkan (`parse_status='failed'`) agar tidak hilang tanpa jejak.
- **FR-2.4** Balas `OK: <n>` dengan `n` = jumlah record yang tersimpan.
- **FR-2.5** Punch duplikat tidak membuat baris baru dan tidak dihitung di `n`.
- **FR-2.6** `table=OPERLOG` diterima dan disimpan, tapi tidak diproses jadi absensi.
- **FR-2.7** Body mentah selalu tersimpan di `iclock_request.body_raw`.

### FR-3 Sinkronisasi user
- **FR-3.1** `table=USERINFO` diparse menjadi `device_user`.
- **FR-3.2** Server dapat mengantri `DATA UPDATE USERINFO` dan `DATA DELETE USERINFO`.
- **FR-3.3** Perubahan user pada device (lewat `USERINFO`) **tidak** otomatis
  menimpa data karyawan internal — hanya tercatat sebagai kondisi device,
  ditandai `sync_status='device_only'` untuk ditinjau admin.

### FR-4 Antrian perintah
- **FR-4.1** `GET /iclock/getrequest?SN=<sn>` mengembalikan semua perintah
  `pending` untuk device itu, dalam satu respons, satu per baris.
- **FR-4.2** Perintah yang sudah dikirim diubah menjadi status `sent` dan
  dicatat `sent_at`. Perintah yang sama **tidak dikirim dua kali** dalam kondisi normal.
- **FR-4.3** Bila tidak ada perintah, balas `OK` (bukan body kosong).
- **FR-4.4** Perintah yang `sent` tapi tidak pernah dikonfirmasi dalam
  **15 menit** dikembalikan ke `pending` (dengan `attempt_count` naik).
  Setelah 3 percobaan, tandai `failed`.
- **FR-4.5** Nilai field perintah divalidasi: tolak `\r`, `\n`, dan TAB di dalam
  nilai; tolak juga karakter kontrol lain. Ini mencegah command injection (§2.6 butir 5).

### FR-5 Konfirmasi perintah
- **FR-5.1** `POST /iclock/devicecmd` memarse baris `ID=<n>&Return=<k>&CMD=<c>`.
  Satu POST bisa berisi **beberapa baris** (batch).
- **FR-5.2** Perbarui `command_queue` menjadi `acked` bila `Return=0`, atau
  `failed` bila negatif, dan simpan `return_code` + `response_raw`.
- **FR-5.3** Bila `Return=-1004` (fitur tidak didukung), tandai kapabilitas
  device agar perintah sejenis tidak dikirim lagi.
- **FR-5.4** Balas `OK`.

### FR-6 API internal
- **FR-6.1** `GET /api/devices` — daftar device + status online/offline.
  Device dianggap **offline** bila `last_seen_at` > 3 × `Delay`.
- **FR-6.2** `POST /api/devices/{id}/approve` — aktivasi device baru.
- **FR-6.3** `GET /api/attendance?from=&to=&device_id=&pin=` — baca absensi.
- **FR-6.4** `POST /api/devices/{id}/commands` — antrikan perintah (tervalidasi).
- **FR-6.5** `POST /api/devices/{id}/commands/query-users` — minta user dari device.

### FR-7 Sinkronisasi dua arah sidik jari
- **FR-7.1** Server dapat mendorong user + template sidik jari ke device
  (server → device) memakai `DATA UPDATE USERINFO`.
- **FR-7.2** Server dapat menarik template dari device (device → server) dengan
  `DATA QUERY USERINFO` lalu membaca push `table=USERINFO` / template.
- **FR-7.3** Setiap perubahan template menaikkan `version` dan menyetel
  `sync_state='pending_push'`.
- **FR-7.4** Aturan konflik (lihat `docs/SCHEMA.md` §13.1):
  versi lebih tinggi menang; versi sama + isi berbeda → `conflict`,
  dicatat di `sync_log`, menunggu keputusan admin.
- **FR-7.5** **Sistem tidak boleh menimpa template sidik jari secara
  diam-diam.** Ragu = tandai `conflict`.
- **FR-7.6** Blob template disimpan **byte persis** seperti diterima. Dilarang
  memotong, mengubah, atau menormalkan isi template.
- **FR-7.7** `sync_log` hanya mencatat `applied`, `conflict`, dan `failed`.
  Kejadian `skipped` normal tidak dicatat (hanya dihitung sebagai metrik)
  agar tabel tidak membanjir.

### FR-8 Jadwal shift & perhitungan keterlambatan
- **FR-8.1** Admin dapat mendefinisikan shift (`start_time`, `end_time`,
  `late_tolerance_min`, `work_days`), termasuk **shift lewat tengah malam**.
- **FR-8.2** Admin dapat menugaskan shift ke karyawan per rentang tanggal.
- **FR-8.3** Job terjadwal mengolah `attendance_log` → `daily_attendance`
  dengan `first_in`, `last_out`, `late_minutes`, `overtime_minutes`, `status`.
- **FR-8.4** Punch setelah tengah malam pada shift malam dipetakan ke
  `work_date` **hari sebelumnya** (bukan hari kalender).
- **FR-8.5** Punch tidak lengkap (hanya masuk tanpa keluar) → status
  `incomplete`, **bukan** `absent` dan **bukan** `present`.
- **FR-8.6** Hari libur (`holiday`) dan hari non-kerja (`work_days`) tidak
  dihitung alpa.
- **FR-8.7** `late_minutes` tidak pernah negatif; toleransi dikurangi lebih dulu.
- **FR-8.8** Koreksi manual admin (`is_manual=1`) **tidak boleh** ditimpa job
  otomatis.
- **FR-8.9** Job perhitungan bersifat **idempoten** — dijalankan berulang kali
  menghasilkan hasil sama, aman diulang.

### FR-9 Retensi data
- **FR-9.1** `body_raw` pada `iclock_request` > 7 hari dipadatkan (di-NULL-kan),
  kecuali baris `failed` dan `USERINFO`.
- **FR-9.2** `iclock_request` > 30 hari dihapus, **kecuali**
  `process_status='failed'` (itu yang nanti perlu diproses ulang).
- **FR-9.3** Penghapusan berjalan per batch (`LIMIT 5000`) agar tidak mengunci
  tabel.
- **FR-9.4** Request `failed` diarsipkan ke storage sebelum dihapus pada 90 hari.

---

### NFR-1 Performa
- Respons `/iclock/*` < 200 ms (p95). Device memakai timeout pendek.
- Ingest 500 punch dalam satu POST harus selesai < 2 detik.

### NFR-2 Ketahanan
- Server **tidak boleh** membalas 5xx ke device bila bisa dihindari — device
  akan menganggap gagal dan mengirim ulang selamanya.
- Bila DB sedang mati, simpan body mentah ke file log darurat lalu balas `OK`,
  supaya data bisa diputar ulang nanti. (Keputusan sadar: mengorbankan
  real-time demi mencegah kehilangan data.)
- Semua endpoint `/iclock/*` **tidak boleh** memakai CSRF atau session cookie.

### NFR-3 Keamanan
- Firmware ZKTeco lama hanya mengizinkan URL statis, jadi autentikasi
  memakai **token di path**:
  `POST /iclock/cdata/<device_token>?SN=...`
  Token 32+ karakter acak, disimpan di-hash (bukan plaintext).
- **Wajib:** validasi panjang body (mis. maks 5 MB) dan batas jumlah baris,
  untuk mencegah abuse pada endpoint yang tidak ber-auth user.
- Semua input device dianggap **tidak tepercaya**: `SN`, `table`, `c`, dan
  seluruh field perintah divalidasi terhadap allowlist.
- **`Shell` command dinonaktifkan secara default** (`ALLOW_SHELL_COMMAND=false`),
  karena mengeksekusi perintah OS di device.
- Jangan pernah mengembalikan detail exception ke device.

### NFR-4 Observabilitas
- Setiap request `/iclock/*` dicatat: SN, table, jumlah baris, durasi, hasil.
- Metrik: punch diterima/menit, punch duplikat/menit, device online, perintah gagal.
- Endpoint `GET /health` yang sudah ada diperluas dengan status antrian perintah.

### NFR-5 Kompatibilitas
- Wajib diuji terhadap varian ATTLOG yang benar-benar dikirim **X100C**.
- Wajib benar terhadap device yang mengirim ulang setelah jaringan pulih.
- Balasan handshake memakai **CRLF**; ini pernah jadi penyebab device diam.
- Handshake menyertakan `TimeZone=7` untuk WIB (dipakai referensi implementasi
  X100-C). **Jadikan ini konfigurasi**, bukan hardcode — server bisa dipakai
  di zona waktu lain, dan `TimeZone` yang salah akan menggeser jam device.

### NFR-6 Keamanan data biometrik
Template sidik jari adalah **data pribadi sensitif** dan tidak bisa diganti
seperti password.
- Tabel `finger_template` **tidak** boleh terekspos di API publik.
- Blob template **tidak pernah** dikirim ke browser/client.
- Akses baca blob wajib dicatat (audit).
- Pertimbangkan enkripsi at-rest.
- Sediakan mekanisme hapus permanen saat karyawan berhenti (hak penghapusan
  data sesuai regulasi PDP).

### NFR-7 Kapasitas device X100C
- Kapasitas log device **100.000 record**. Bila penuh sebelum tersinkron,
  punch lama **terhapus di device dan hilang permanen**.
- Sistem **wajib** memantau `AttLogCount` (via `GET OPTION`) dan memberi
  peringatan pada ambang tertentu (mis. 70%).
- Kapasitas sidik jari 3.200 slot; pantau `UserCount`/`FPCount`.

---

## 6. Kriteria penerimaan

| # | Skenario | Ekspektasi |
|---|---|---|
| AC-1 | Device baru pertama kali connect | Tercatat sebagai `unregistered`, dibalas konfigurasi, tidak error |
| AC-2 | Device terdaftar kirim 3 punch ATTLOG | 3 baris di `attendance_log`, balasan `OK: 3` |
| AC-3 | Device kirim ulang batch yang sama | Tetap 3 baris, balasan `OK: 0` |
| AC-4 | Kirim ATTLOG varian A, B, C | Ketiganya terparse benar, `raw_fields` menyimpan aslinya |
| AC-5 | Server antrikan `DATA UPDATE USERINFO` | Muncul di respons `getrequest` berikutnya sebagai `C:<id>:DATA UPDATE ...` |
| AC-6 | Device balas `ID=<id>&Return=0&CMD=DATA` | Baris jadi `acked`, tidak dikirim lagi |
| AC-7 | Device balas `Return=-1002` | Baris jadi `failed`, `return_code` tersimpan |
| AC-8 | Perintah `sent` 15 menit tanpa konfirmasi | Kembali ke `pending` |
| AC-9 | Nama user berisi `\n` | Ditolak di validasi, tidak masuk antrian |
| AC-10 | DB mati saat ingest | Body tersimpan di darurat, device tetap dapat `OK` |
| AC-11 | Operlog masuk | Tersimpan, `table='OPERLOG'`, tidak muncul di daftar absensi |
| AC-12 | Satu PIN, dua slot jari berbeda | **Dua** baris `finger_template` tersimpan |
| AC-13 | Slot jari sama untuk PIN sama dua kali | Ditolak `uk_finger_slot` (duplikat dicegah) |
| AC-14 | Template diubah ulang | `version` naik, `sync_state='pending_push'` |
| AC-15 | Versi sama, isi berbeda | `sync_state='conflict'`, tercatat di `sync_log` |
| AC-16 | Hapus shift yang masih ditugaskan | **Ditolak** (`RESTRICT`), shift tetap ada |
| AC-17 | Job hitung ulang jalan dua kali | Hasil sama, tidak ada baris ganda di `daily_attendance` |
| AC-18 | Koreksi manual lalu job jalan | Nilai manual **tidak** tertimpa |
| AC-19 | Shift malam 22:00–06:00, punch 02:00 | Masuk `work_date` hari sebelumnya |
| AC-20 | Punch hanya masuk tanpa keluar | `status='incomplete'`, bukan `absent` |
| AC-21 | Tanggal hari libur | Tidak ada `absent`; status `holiday` |
| AC-22 | Karyawan telat 5 menit, toleransi 10 | `late_minutes = 0` (tidak negatif) |
| AC-23 | Pembersihan retensi | `failed` **tidak** terhapus; `body_raw` lama dipadatkan |

---

## 7. Tahapan implementasi

| Fase | Isi | Definisi selesai |
|---|---|---|
| **F0** | Verifikasi firmware X100C mendukung PUSH/ADMS | Satu device benar-benar memanggil server kita |
| **F1** | Migrasi skema DB (001 + 002) | Kedua migrasi jalan bersih, 13 tabel terbentuk |
| **F2** | Handshake + registrasi device (FR-1) | AC-1 lulus, device nyata dapat konfigurasi |
| **F3** | Parser + ingest ATTLOG (FR-2) | AC-2, AC-3, AC-11 lulus |
| **F4** | Antrian & perintah (FR-4, FR-5) | AC-5..AC-9 lulus |
| **F5** | API internal (FR-6) | Device bisa disetujui & dipantau |
| **F6** | Sinkronisasi user + sidik jari (FR-3, FR-7) | AC-12..AC-15, AC-5 lulus |
| **F7** | Jadwal shift & perhitungan (FR-8) | AC-16..AC-22 lulus |
| **F8** | Pengerasan, retensi, observabilitas (FR-9, NFR) | AC-10, AC-23 lulus, metrik terlihat |

**F0 adalah gerbang wajib.** Bila firmware X100C tidak mendukung PUSH/ADMS,
F1–F8 tidak ada gunanya karena tidak akan ada data yang masuk. Selesaikan F0
lebih dulu, dengan satu device nyata.

**F2 dan F3 adalah jalur kritis** — tanpa keduanya tidak ada data yang masuk.

---

## 8. Risiko

| Risiko | Dampak | Mitigasi |
|---|---|---|
| **Firmware X100C tidak punya ADMS** | Proyek tidak bisa jalan sama sekali | **F0: verifikasi lebih dulu** dengan device nyata; siapkan firmware upgrade |
| Firmware berbeda-beda perilakunya | Parser gagal di sebagian device | Simpan data mentah; parser multi-varian; uji dengan device nyata |
| Device mengirim ulang tanpa henti | Tabel membengkak | UNIQUE hash + balas `OK` selalu |
| URL statis membocorkan token | Device lain bisa menyuntik data | Token per device, rotasi token, pantau SN tak dikenal |
| `Shell` disalahgunakan | Device rusak permanen | Nonaktif default, butuh flag eksplisit + audit |
| Zona waktu salah | Absensi bergeser | `TimeZone` jadi konfigurasi; simpan UTC + offset device |
| Jam device tidak akurat | Punch tercatat di waktu salah | Sediakan sinkronisasi waktu opsional, jangan paksa |
| **Template sidik jari tertimpa salah saat sync 2 arah** | Karyawan harus rekam ulang; data hilang permanen | Versi + `sync_state`; ragu → `conflict`; jangan pernah timpa diam-diam |
| **Log device X100C penuh (100.000)** | Punch lama hilang permanen di device | Pantau `AttLogCount`, peringatan di 70%, ambil log berkala |
| **Salah urai format template** | Blob rusak, tidak bisa dipulihkan | Simpan byte mentah; jangan parse/ubah; verifikasi dengan round-trip ke device |
| Shift malam salah dipetakan | Semua karyawan shift malam "alpa" | Aturan `effective_work_date`; AC-19 wajib lulus |
| Koreksi manual tertimpa job | Data kehadiran salah, kepercayaan hilang | `is_manual` + pola `IF(is_manual=1, ...)`; AC-18 wajib lulus |
| Data biometrik bocor | Pelanggaran privasi / regulasi | Blob tidak keluar API; audit akses; enkripsi at-rest |

---

## 9. Pertanyaan terbuka (sisa)

Keputusan #1–#5 sudah dijawab dan sudah tercermin di dokumen ini serta skema.
Yang masih perlu dijawab **saat implementasi berjalan**:

1. **Apakah X100C yang ada sudah ber-firmware ADMS?** (paling mendesak —
   lihat F0)
2. **Berapa banyak user per device, dan berapa slot jari per user?**
   Menentukan kebutuhan penyimpanan `finger_template` (perkiraan kasar:
   ~30–60 MB/device bila penuh).
3. **Aturan konflik sync yang mana yang dipakai default** — `server_wins`,
   `device_wins`, atau selalu `manual`? Disarankan **`manual`** untuk sidik
   jari, karena taruhannya karyawan harus rekam ulang.
4. **Perlu sinkronisasi waktu otomatis ke device?** Bila device jarang
   disetel dan jamnya melenceng, semua absensi bergeser. Bisa dipakai
   `Shell date` atau `TimeZone`, tetapi keduanya punya efek samping.
5. **Di mana template sidik jari diarsipkan** bila jumlah device bertambah —
   tetap di MySQL atau pindah ke object storage?
