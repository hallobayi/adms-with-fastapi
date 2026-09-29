# PRD — Implementasi ZKTeco iClock / ADMS Push Protocol

**Proyek:** ADMS (Attendance Device Management System)
**Versi dokumen:** 1.0
**Tanggal:** 2026-09-29
**Status:** Draft untuk implementasi
**Stack:** FastAPI + MySQL 8 (`app/` yang sudah direfactor)

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

### 1.2 Non-tujuan (di luar cakupan v1)

- Penarikan template sidik jari / wajah (FINGERTMP, FACE) — ditunda.
- Manajemen akses pintu (door control), alarm, dan interlock.
- Aplikasi web UI penuh untuk manajemen karyawan (hanya API + halaman monitor sederhana).

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
  models/                          # model SQLAlchemy / skema MySQL
  routers/
    devices.py                     # API internal: kelola device (auth JWT)
    attendance.py                  # API internal: baca absensi
    commands.py                    # API internal: antrikan perintah ke device
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

---

## 5. Kebutuhan non-fungsional

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
- Wajib diuji terhadap varian ATTLOG A, B, dan C.
- Wajib benar terhadap device yang mengirim ulang setelah jaringan pulih.
- Balasan handshake memakai **CRLF**; ini pernah jadi penyebab device diam.

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

---

## 7. Tahapan implementasi

| Fase | Isi | Definisi selesai |
|---|---|---|
| **F1** | Migrasi skema DB (§4 dokumen skema) | Migrasi jalan naik & turun bersih |
| **F2** | Handshake + registrasi device (FR-1) | AC-1 lulus, device nyata dapat konfigurasi |
| **F3** | Parser + ingest ATTLOG (FR-2) | AC-2, AC-3, AC-4, AC-11 lulus |
| **F4** | Antrian & perintah (FR-4, FR-5) | AC-5..AC-9 lulus |
| **F5** | API internal (FR-6) | Device bisa disetujui & dipantau |
| **F6** | Sinkronisasi user (FR-3) | AC-5 mencakup USERINFO |
| **F7** | Pengerasan + observabilitas (NFR) | AC-10 lulus, metrik terlihat |

**F2 dan F3 adalah jalur kritis** — tanpa keduanya tidak ada data yang masuk.

---

## 8. Risiko

| Risiko | Dampak | Mitigasi |
|---|---|---|
| Firmware berbeda-beda perilakunya | Parser gagal di sebagian device | Simpan data mentah; parser multi-varian; uji dengan device nyata |
| Device mengirim ulang tanpa henti | Tabel membengkak | UNIQUE hash + balas `OK` selalu |
| URL statis membocorkan token | Device lain bisa menyuntik data | Token per device, rotasi token, pantau SN tak dikenal |
| `Shell` disalahgunakan | Device rusak permanen | Nonaktif default, butuh flag eksplisit + audit |
| Zona waktu salah | Absensi bergeser | Jangan kirim `TimeZone`; simpan UTC + offset device |
| Jam device tidak akurat | Punch tercatat di waktu salah | Sediakan sinkronisasi waktu opsional, jangan paksa |

---

## 9. Pertanyaan terbuka

1. **Model device apa saja** yang akan dipakai? Ini menentukan varian ATTLOG
   yang perlu diuji dan kapabilitas yang tersedia.
2. Apakah perlu penarikan **template wajah** (FINGERTMP/BIOPHOTO)? Berdampak
   besar pada kebutuhan penyimpanan.
3. Perlukah **sinkronisasi dua arah** user (server → device dan device → server
   saling menimpa), atau satu arah saja?
4. Berapa **retensi** `iclock_request`? Tabel ini tumbuh paling cepat — usul
   awal 30 hari, lalu body mentah dipadatkan.
5. Apakah absensi perlu dihubungkan ke **jadwal shift** untuk menghitung
   keterlambatan, atau cukup menyimpan punch mentah dulu?
