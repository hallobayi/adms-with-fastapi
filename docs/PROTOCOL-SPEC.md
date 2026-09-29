# ZKTeco iClock / ADMS Push Protocol — Referensi Teknis

Dirangkum dari implementasi yang diverifikasi di perangkat keras
(`s0x90/zkteco-adms`, firmware SpeedFace-V5L-RFID / ZAM180-NF v1.1.17) dan
implementasi server lain. Dokumen ini adalah rujukan saat menulis parser.

---

## 0. Device target: ZKTeco X100C

**Penting:** ADMS adalah **fungsi opsional** pada X100C. Verifikasi firmware
sebelum memulai (lihat PRD §0.1).

| Item | Nilai | Relevansi |
|---|---|---|
| Kapasitas sidik jari | 3.200 | Batas jumlah slot user |
| Kapasitas log | 100.000 | **Bila penuh, punch lama terhapus di device** |
| Komunikasi | TCP/IP, USB | Push lewat TCP/IP |
| Verifikasi | Fingerprint, PIN, kartu RFID (opsional) | Tidak ada wajah |
| Display | 3 inci | — |
| Zona waktu | `TimeZone=7` (WIB) | Jadikan konfigurasi |

### 0.1 Yang dikonfirmasi berjalan di X100-C

Dari implementasi referensi yang diuji pada X100-C:

- ✅ Handshake `GET /iclock/cdata?SN=` → balasan `GET OPTION FROM: ...` CRLF
- ✅ `POST /iclock/cdata?table=ATTLOG` dengan body tab-separated
- ✅ Balasan `OK: <jumlah>` diterima device
- ✅ `GET /iclock/getrequest` → device menerima `OK` saat tidak ada perintah
- ✅ `TransFlag=1111000000`, `Realtime=1`, `Stamp=9999`, `Delay=30`,
  `ErrorDelay=60`
- ✅ `TimeZone=7` dipakai (dikomentari di referensi, jadi opsional)

### 0.2 Yang **belum** terkonfirmasi untuk X100C

- ⚠️ **Format blob template sidik jari.** Referensi X100-C tidak menguraikan
  struktur template sama sekali — hanya menyimpan body mentah. Header 6 byte
  (`size`/`uid`/`finger_id`/`flag`) berasal dari keluarga ZKTeco lain dan
  **belum tentu** berlaku di X100C.
  → **Jangan bangun logika pada asumsi format.** Simpan blob apa adanya, dan
  verifikasi dengan uji round-trip (tarik → kirim ulang → cek verifikasi di
  device).
- ⚠️ Perintah untuk mengirim template **ke** device pada X100C belum
  diverifikasi. Perlu diuji langsung.
- ⚠️ Varian ATTLOG yang benar-benar dipakai X100C. Referensi menunjukkan
  pemisahan **tab** dengan minimal 6 kolom (`employee_id`, `timestamp`,
  `status1`..`status5`), konsisten dengan Varian B di bawah.

---

## 1. Endpoint

| Path | Method | Auth | Fungsi |
|---|---|---|---|
| `/iclock/cdata` | GET | Token device | Handshake, minta konfigurasi |
| `/iclock/cdata` | POST | Token device | Kirim ATTLOG / OPERLOG / USERINFO / OPTIONS |
| `/iclock/getrequest` | GET | Token device | Poll perintah |
| `/iclock/devicecmd` | POST | Token device | Lapor hasil eksekusi |
| `/iclock/ping` | GET | Token device | Heartbeat (tidak ada di semua firmware) |
| `/iclock/registry` | GET/POST | Token device | Registrasi & kapabilitas |

Semua balasan `Content-Type: text/plain`.

---

## 2. Handshake

### Request
```
GET /iclock/cdata?SN=ABC123456 HTTP/1.1
```

### Response (CRLF di setiap baris — WAJIB)
```
GET OPTION FROM: ABC123456\r\n
Stamp=9999\r\n
OpStamp=1759132800\r\n
ErrorDelay=60\r\n
Delay=30\r\n
ResLogDay=18250\r\n
ResLogDelCount=10000\r\n
ResLogCount=50000\r\n
TransTimes=00:00;14:05\r\n
TransInterval=1\r\n
TransFlag=1111000000\r\n
Realtime=1\r\n
Encrypt=0\r\n
```

### Parameter

| Key | Nilai | Arti |
|---|---|---|
| `GET OPTION FROM` | `<SN>` | Echo SN device |
| `Stamp` | `9999` | Versi konfigurasi (konstanta; nilai tinggi memaksa device menerapkan) |
| `OpStamp` | unix ts | Versi konfigurasi operasi |
| `ErrorDelay` | 60 | Detik tunggu sebelum retry setelah error |
| `Delay` | 30 | Interval poll `getrequest` (detik) |
| `TransTimes` | `HH:MM;HH:MM` | Jendela waktu transmisi |
| `TransInterval` | 1 | Pengali interval |
| `TransFlag` | 10 digit | Bitmask tabel yang dikirim |
| `Realtime` | `1`/`0` | Kirim punch segera |
| `Encrypt` | `0` | Nonaktifkan enkripsi |
| `TimeZone` | menit | **Konfigurasi**, jangan hardcode. `420` = WIB (UTC+7). Menggeser jam device. |

### 2.1 Handshake yang dikonfirmasi di X100-C

Blok ini sudah terbukti diterima X100-C (dengan `TimeZone=7` sebagai opsi;
referensi aslinya mengomentari baris itu, jadi device tetap jalan tanpanya):

```
GET OPTION FROM: <SN>\r\n
Stamp=9999\r\n
OpStamp=<unix_ts>\r\n
ErrorDelay=60\r\n
Delay=30\r\n
ResLogDay=18250\r\n
ResLogDelCount=10000\r\n
ResLogCount=50000\r\n
TransTimes=00:00;14:05\r\n
TransInterval=1\r\n
TransFlag=1111000000\r\n
TimeZone=7\r\n
Realtime=1\r\n
Encrypt=0
```

**Catatan tentang `TimeZone`:** referensi memakai `TimeZone=7` untuk WIB, tapi
nilai ini **bukan** offset menit standar — beberapa firmware menerimanya
sebagai jam, yang lain sebagai menit. Karena efeknya menggeser jam device,
kirim hanya bila memang ingin menyetel waktu device, dan **verifikasi
hasilnya** dengan membandingkan `punch_at` device vs jam nyata sebelum
mengaktifkannya di produksi.

### 2.2 TransFlag (10 digit, urut kiri ke kanan)
```
1 1 1 1 0 0 0 0 0 0
│ │ │ │ └─┴─┴─┴─┴── reserved
│ │ │ └── USERINFO / user
│ │ └──── OPERLOG
│ └────── ATTLOG
└──────── (selalu 1)
```
`TransFlag=1111000000` berarti: ATTLOG + OPERLOG + USERINFO aktif.

**Jebakan:** bila `TransFlag` tidak mengaktifkan ATTLOG, device **tidak akan
pernah** mengirim absensi. Ini penyebab paling umum "device connect tapi tidak
ada data".

---

## 3. Ingest data

### 3.1 ATTLOG

```
POST /iclock/cdata?SN=ABC123456&table=ATTLOG&Stamp=42 HTTP/1.1
Content-Type: text/plain

1001	2026-09-29 08:30:00	0	1	0
1002	2026-09-29 08:30:05	1	15	0
```

**Varian A (5 kolom, tab):**
`PIN · DateTime · Status · Verify · WorkCode`

**Varian B (6–11 kolom, tab):** kolom ke-3 dst = Status1..StatusN (reserved)
`PIN · DateTime · Status · Status2 · Status3 · Status4`

**Varian C (key=value, tab atau spasi):**
`PIN=1001 · DateTime=2026-09-29 08:30:00 · Verified=1 · Status=0`

**Timestamp:** `YYYY-MM-DD HH:MM:SS` atau Unix epoch detik.

**Status:** `0`=Check In, `1`=Check Out, `2`=Break Out, `3`=Break In,
`4`=Overtime In, `5`=Overtime Out

**Verify:** `0`=Password, `1`=Fingerprint, `2`=Card, `3`=Password,
`4`=Card, `5`=Fingerprint+Card, `6`=Fingerprint+Password, `7`=Card+Password,
`8`=Card+Fingerprint+Password, `9`=Other, `15`=Face, `25`=Palm

**Balasan:** `OK: <jumlah_tersimpan>` — atau cukup `OK` di sebagian firmware.

### 3.2 OPERLOG
Format serupa, berisi event operasi device (buka pintu, alarm). Simpan, jangan
proses jadi absensi.

### 3.3 USERINFO
```
POST /iclock/cdata?SN=ABC123456&table=USERINFO HTTP/1.1

PIN=1001	Name=John Doe	Privilege=0	Card=12345678
PIN=1002	Name=Alice	Privilege=14	Card=87654321
```
`Privilege`: `0`=user biasa, `14`=admin.

### 3.4 OPTIONS / registry
```
POST /iclock/cdata?SN=ABC123456&table=options&c=registry HTTP/1.1
X-Device-Type: SpeedFace-V5L-RFID[TI]

DeviceType=acc,~DeviceName=SpeedFace-V5L-RFID[TI],FirmVer=ZAM180-NF-Ver1.1.17,IPAddress=192.168.1.201
```
Key boleh berawalan `~` — **tilde harus dilepas** saat parsing.
Balasan: `OK`.

---

## 4. Perintah (getrequest → devicecmd)

### 4.1 Poll
```
GET /iclock/getrequest?SN=ABC123456 HTTP/1.1
```

Balasan bila ada perintah (CRLF antar baris):
```
C:15:DATA QUERY USERINFO\r\n
C:16:DATA UPDATE USERINFO PIN=1003\tName=Bob Marley\tPrivilege=0\tCard=99887766\r\n
```

Balasan bila kosong:
```
OK
```

### 4.2 Format wire
```
C:<ID>:<CMD>\n
```
`<ID>` = integer naik monoton, dialokasikan server **saat perintah diantrikan**.
Dipakai untuk korelasi dengan `devicecmd`.

### 4.3 Kosakata perintah terverifikasi

| Perintah wire | CMD echo | Catatan |
|---|---|---|
| `INFO` | `INFO` | Info lengkap device |
| `CHECK` | `CHECK` | Heartbeat |
| `GET OPTION FROM <key>` | `GET OPTION` | Nilai dikirim lewat cdata, bukan balasan |
| `DATA UPDATE USERINFO PIN=<p>\tName=<n>\tPrivilege=<v>\tCard=<c>` | `DATA` | Tab-separated |
| `DATA DELETE USERINFO PIN=<p>` | `DATA` | |
| `DATA QUERY USERINFO` | `DATA` | Data dikirim lewat cdata `table=USERINFO` |
| `DATA QUERY USERINFO PIN=<p>` | `DATA` | Satu user |
| `LOG` | `LOG` | Minta log |
| `Shell <cmd>` | `Shell` | **Berbahaya**, nonaktif default |

### 4.4 Jebakan terverifikasi

1. **`USER ADD` / `USER DEL` ditolak `-1002`.** Datasheet salah. Pakai
   `DATA UPDATE USERINFO` / `DATA DELETE USERINFO`.
2. **`DATA DEL` ditolak.** Harus `DELETE` penuh.
3. **`DATA QUERY` tidak membalas data.** Data datang lewat
   `POST /iclock/cdata?table=USERINFO`.
4. **Pemisah field = TAB**, bukan spasi.
5. **Nama user bisa mengandung spasi** (`Bob Marley`) — karena itu TAB wajib.
6. **Injection:** newline/CR di nilai field bisa menyuntik baris perintah baru.
   Wajib ditolak.

### 4.5 Konfirmasi
```
POST /iclock/devicecmd?SN=ABC123456 HTTP/1.1
Content-Type: text/plain

ID=15&Return=0&CMD=DATA
ID=16&Return=0&CMD=DATA
```

Bisa **banyak baris** dalam satu POST. Balasan server: `OK`.

| Return | Arti |
|---|---|
| `0` | Sukses |
| `-1` | Tidak didukung / tidak ada data |
| `-2` | Operasi file gagal |
| `-1002` | Sintaks tidak valid |
| `-1004` | Tabel/fitur tidak didukung model ini |

---

## 5. Nilai `GET OPTION` yang dikenal

`DeviceName`, `FWVersion`, `IPAddress`, `MACAddress`, `Platform`, `WorkCode`,
`LockCount`, `UserCount`, `FPCount`, `AttLogCount`, `FaceCount`,
`TransactionCount`, `MaxUserCount`, `MaxAttLogCount`, `MaxFingerCount`,
`MaxFaceCount`

---

## 6. Setup device X100C

Dari dokumentasi resmi ZKTeco. **Prasyarat:** firmware sudah punya fitur
PUSH/ADMS (fungsi opsional pada X100C — lihat PRD §0.1).

```
Menu > Comm > Cloud Server setting
    Server Address : <IP atau domain server ADMS>
    Server Port    : <port ADMS>
```

Pastikan jaringan device benar:

```
Menu > Comm > Ethernet
    IP Address / Subnet Mask / Gateway / DNS  → sesuai jaringan server
```

Setelah disimpan, device memanggil `GET /iclock/cdata?SN=<SN>` dalam beberapa
detik hingga satu menit.

**Cara membuktikan device benar-benar terhubung:** periksa baris baru di tabel
`iclock_request` dengan `endpoint='cdata'`. Kalau tabel itu tetap kosong,
masalahnya ada di **jaringan atau firmware device — bukan di kode server**.
Ini langkah diagnosis pertama yang paling berguna, dan menghemat waktu
sebelum mulai mencurigai parser.

---

## 7. Template sidik jari — status pengetahuan

### 7.1 Yang diketahui

- Device ZKTeco mendukung hingga **10 slot jari per user** (indeks 0–9).
- Sebagian keluarga ZKTeco memakai **header 6 byte**: offset 0–1 = ukuran
  (little-endian), 2–3 = UID (little-endian), 4 = finger ID, 5 = flag.
- Blob template bersifat biner dan **tidak** dikirim sebagai teks.

### 7.2 Yang **tidak** diketahui untuk X100C

- Apakah header 6 byte itu berlaku. Implementasi referensi X100-C **tidak**
  menguraikan template — hanya menyimpan body mentah.
- Perintah tepat untuk mengirim template **ke** X100C.
- Ukuran pasti satu template pada X100C.

### 7.3 Aturan yang harus dipatuhi

> **Simpan blob template byte persis seperti diterima. Jangan memotong,
> mengubah, atau menormalkan.**

Alasannya: template sidik jari tidak bisa direkonstruksi. Bila blob rusak
karena kita "membantu" menafsirkannya, satu-satunya jalan keluar adalah
memanggil karyawan untuk merekam ulang. Menyimpan byte mentah selalu aman.

### 7.4 Cara memverifikasi tanpa tahu formatnya

Tidak perlu memahami struktur template untuk membuktikan implementasi benar:

1. Tarik template dari device → simpan blob.
2. Kirim blob itu kembali ke device **tanpa perubahan apa pun**.
3. Coba verifikasi sidik jari user tersebut di device.

Bila langkah 3 berhasil, format sudah benar. Ini uji round-trip, dan jauh
lebih dapat diandalkan daripada menebak layout byte.

---

## 8. Referensi

- `s0x90/zkteco-adms` — library Go, detail perintah diverifikasi di perangkat keras
- `saifulcoder/adms-server-ZKTeco` — implementasi Laravel, **diuji pada X100-C**
- Dokumentasi ZKTeco: ADMS Settings on the device (Menu > Comm > Cloud Server)
- Spesifikasi ZKTeco PUSH SDK v2.3 / v3.1.2 (dokumen resmi, catatan: sebagian
  sintaks di dokumen sudah usang)
