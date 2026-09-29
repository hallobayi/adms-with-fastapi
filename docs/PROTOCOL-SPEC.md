# ZKTeco iClock / ADMS Push Protocol — Referensi Teknis

Dirangkum dari implementasi yang diverifikasi di perangkat keras
(`s0x90/zkteco-adms`, firmware SpeedFace-V5L-RFID / ZAM180-NF v1.1.17) dan
implementasi server lain. Dokumen ini adalah rujukan saat menulis parser.

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
| `TimeZone` | menit | **Hindari** — menggeser jam device |

### TransFlag (10 digit, urut kiri ke kanan)
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

## 6. Referensi

- `s0x90/zkteco-adms` — library Go, detail perintah diverifikasi di perangkat keras
- Spesifikasi ZKTeco PUSH SDK v2.3 / v3.1.2 (dokumen resmi, catatan: sebagian
  sintaks di dokumen sudah usang)
