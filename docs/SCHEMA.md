# Skema Database — ADMS ZKTeco Push

**DBMS:** MySQL 8.0+ (InnoDB, `utf8mb4`)
**Engine:** semua tabel InnoDB
**Migrasi:** `migrations/001_init_adms_push.sql`

---

## 1. Peta tabel

```
                    ┌──────────────────┐
                    │     device       │ 1 device = 1 mesin ZKTeco
                    │  (SN, token,     │
                    │   delay, opt)    │
                    └────────┬─────────┘
                             │
        ┌────────────────────┼────────────────────┬──────────────────┐
        │                    │                    │                  │
        ▼                    ▼                    ▼                  ▼
┌───────────────┐  ┌──────────────────┐  ┌──────────────┐  ┌────────────────┐
│ iclock_request│  │  attendance_log  │  │ command_queue│  │  device_user   │
│ body mentah   │  │  (punch absensi) │  │ antri perintah│ │  user di device│
│ semua request │  │  UNIQUE hash     │  │ C:<id>:<cmd> │  │  (mirror)      │
└───────────────┘  └──────────────────┘  └──────────────┘  └────────────────┘
                             │
                             ▼
                   ┌──────────────────┐
                   │    employee      │  data karyawan internal
                   │  (pin, nama)     │  (sumber kebenaran)
                   └──────────────────┘
```

**Alur data:** `iclock_request` menyimpan **setiap** request apa adanya →
parser menulis ke `attendance_log` / `device_user`. Tabel mentah inilah yang
membuat kita bisa memperbaiki parser lalu memproses ulang data lama.

---

## 2. Tabel `device`

Menyimpan device yang terdaftar beserta konfigurasi yang dikirim saat handshake.

```sql
CREATE TABLE device (
    id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    serial_number   VARCHAR(64)     NOT NULL
                    COMMENT 'SN dari device, dikirim sebagai query param SN',
    token_hash      CHAR(64)        NULL
                    COMMENT 'SHA-256 token push; NULL = belum disetujui',
    display_name    VARCHAR(128)    NULL COMMENT 'Nama ramah, diisi admin',
    location        VARCHAR(191)    NULL COMMENT 'Lokasi fisik, mis. Lobby Lt.1',
    status          ENUM('pending','active','suspended')
                    NOT NULL DEFAULT 'pending'
                    COMMENT 'pending = device connect tapi belum disetujui',
    model           VARCHAR(64)     NULL COMMENT 'mis. SpeedFace-V5L-RFID',
    firmware        VARCHAR(64)     NULL COMMENT 'mis. ZAM180-NF-Ver1.1.17',
    device_type     VARCHAR(32)     NULL COMMENT 'acc / att / multi',
    ip_address      VARCHAR(45)     NULL COMMENT 'IP di jaringan lokal device',
    mac_address     VARCHAR(32)     NULL,

    -- Konfigurasi handshake (dapat diubah per device)
    poll_delay      INT UNSIGNED    NOT NULL DEFAULT 30
                    COMMENT 'Delay= : interval poll getrequest (detik)',
    error_delay     INT UNSIGNED    NOT NULL DEFAULT 60 COMMENT 'ErrorDelay=',
    trans_flag      CHAR(10)        NOT NULL DEFAULT '1111000000'
                    COMMENT 'TransFlag= : bitmask tabel yang dikirim device',
    realtime        TINYINT(1)      NOT NULL DEFAULT 1 COMMENT 'Realtime=',
    stamp_version   INT UNSIGNED    NOT NULL DEFAULT 9999 COMMENT 'Stamp=',

    -- Kapabilitas (dari registry / balikan -1004)
    supports_userinfo TINYINT(1)    NOT NULL DEFAULT 1,
    supports_operlog  TINYINT(1)    NOT NULL DEFAULT 1,
    supports_shell    TINYINT(1)    NOT NULL DEFAULT 0,

    options_json    JSON            NULL COMMENT 'Seluruh key registry yang diterima',

    -- Status runtime
    last_seen_at    DATETIME        NULL COMMENT 'Request terakhir dari device',
    last_handshake_at DATETIME      NULL,
    last_attlog_at  DATETIME        NULL COMMENT 'Punch terakhir yang diterima',
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP
                    ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (id),
    UNIQUE KEY uk_device_sn (serial_number),
    KEY idx_device_status (status),
    KEY idx_device_last_seen (last_seen_at),
    KEY idx_device_token (token_hash)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Device ZKTeco yang terhubung ke server';
```

**Catatan desain:**
- `token_hash`: token disimpan di-hash, bukan plaintext. Firmware lama hanya
  mendukung URL statis, jadi token ditempel di path (`/iclock/cdata/<token>`).
- `status='pending'` penting: device baru **tetap dilayani** saat handshake
  (kalau tidak, ia berhenti mencoba), tetapi data absensinya tidak dipercaya
  sampai admin menyetujui.
- `poll_delay` = `Delay=` di handshake. Menurunkannya membuat data lebih cepat
  masuk tetapi membebani server; jangan di bawah 10 detik.
- `supports_*`: diisi dari registry, atau dari balikan `-1004` di `devicecmd`.
  Ini mencegah server mengirim perintah yang selalu gagal ke model tertentu.

---

## 3. Tabel `iclock_request`

**Seluruh** body request device disimpan apa adanya. Ini jaring pengaman:
kalau parser salah, data masih bisa diproses ulang tanpa meminta device
mengirim ulang (yang belum tentu bisa).

```sql
CREATE TABLE iclock_request (
    id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    device_id       BIGINT UNSIGNED NULL COMMENT 'NULL bila SN belum dikenal',
    serial_number   VARCHAR(64)     NOT NULL,
    endpoint        VARCHAR(32)     NOT NULL
                    COMMENT 'cdata / getrequest / devicecmd / ping / registry',
    http_method     VARCHAR(8)      NOT NULL,
    table_name      VARCHAR(32)     NULL COMMENT 'ATTLOG / OPERLOG / USERINFO / options',
    c_param         VARCHAR(32)     NULL COMMENT 'query param c= (registry/log/data)',
    stamp           VARCHAR(32)     NULL COMMENT 'query param Stamp= dari device',
    op_stamp        VARCHAR(32)     NULL COMMENT 'query param OpStamp=',
    query_string    VARCHAR(1024)   NULL,
    content_type    VARCHAR(128)    NULL,
    body_raw        MEDIUMTEXT      NULL COMMENT 'Body mentah, TIDAK diubah',
    body_bytes      INT UNSIGNED    NOT NULL DEFAULT 0,
    line_count      INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT 'Jumlah baris data',
    parsed_count    INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT 'Baris yang berhasil ditafsirkan',
    stored_count    INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT 'Baris yang benar-benar tersimpan',
    dup_count       INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT 'Baris duplikat yang diabaikan',
    failed_count    INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT 'Baris gagal parse',
    response_body   VARCHAR(255)    NULL COMMENT 'Apa yang kita balas ke device',
    source_ip       VARCHAR(45)     NULL,
    user_agent      VARCHAR(255)    NULL,
    process_status  ENUM('received','processed','failed','skipped')
                    NOT NULL DEFAULT 'received'
                    COMMENT 'failed = perlu diproses ulang setelah parser diperbaiki',
    error_message   TEXT            NULL,
    processed_at    DATETIME        NULL,
    created_at      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),

    PRIMARY KEY (id),
    KEY idx_req_device_created (device_id, created_at),
    KEY idx_req_sn_created (serial_number, created_at),
    KEY idx_req_process (process_status, created_at)
                    COMMENT 'Untuk mencari request yang perlu diproses ulang',
    KEY idx_req_table_created (table_name, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Arsip mentah seluruh request /iclock/*';
```

**Catatan desain:**
- Tabel ini **tumbuh paling cepat**. Rencanakan partisi per bulan atau
  pembersihan rutin (usul: retensi 30 hari, dengan `body_raw` dipadatkan lebih dulu).
- `device_id` boleh `NULL`: request dari device tak dikenal tetap dicatat agar
  bisa dilacak, tapi tidak terhubung ke device mana pun.
- `created_at` memakai presisi milidetik (`DATETIME(3)`) karena beberapa request
  bisa datang dalam detik yang sama — berguna untuk mengurutkan.
- `process_status='failed'` adalah tombol "coba lagi nanti": perbaiki parser,
  lalu jalankan ulang baris-baris ini.

---

## 4. Tabel `employee`

Data karyawan internal — **sumber kebenaran** untuk siapa yang boleh absen.

```sql
CREATE TABLE employee (
    id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    pin             VARCHAR(24)     NOT NULL
                    COMMENT 'PIN di device; penghubung ke attendance_log.pin',
    name            VARCHAR(128)    NOT NULL,
    employee_code   VARCHAR(32)     NULL COMMENT 'NIK / nomor karyawan',
    department      VARCHAR(64)     NULL,
    position        VARCHAR(64)     NULL,
    email           VARCHAR(128)    NULL,
    phone           VARCHAR(32)     NULL,
    joined_at       DATE            NULL,
    resigned_at     DATE            NULL COMMENT 'Terisi = tidak lagi aktif',
    is_active       TINYINT(1)      NOT NULL DEFAULT 1,
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP
                    ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (id),
    UNIQUE KEY uk_employee_pin (pin),
    UNIQUE KEY uk_employee_code (employee_code),
    KEY idx_employee_active (is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Data karyawan internal';
```

**Catatan:** `pin` sengaja `VARCHAR`, bukan `INT` — di lapangan PIN sering
berupa string berawalan nol (`0012`), dan menyimpannya sebagai angka akan
menghilangkan nol di depan.

---

## 5. Tabel `attendance_log`

Inti sistem. Setiap punch dari device menjadi satu baris.

```sql
CREATE TABLE attendance_log (
    id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    device_id       BIGINT UNSIGNED NULL,
    serial_number   VARCHAR(64)     NOT NULL COMMENT 'Disimpan langsung agar aman bila device dihapus',
    pin             VARCHAR(24)     NOT NULL COMMENT 'PIN dari device',
    employee_id     BIGINT UNSIGNED NULL
                    COMMENT 'NULL bila PIN tidak cocok dengan employee mana pun',

    -- Waktu
    punch_at        DATETIME        NOT NULL COMMENT 'Waktu scan menurut DEVICE (bukan server)',
    punch_date      DATE            NOT NULL COMMENT 'punch_at::DATE, untuk grouping cepat',
    device_tz_offset SMALLINT       NULL COMMENT 'Offset zona waktu device dalam menit',

    -- Kode dari device
    status_code     TINYINT         NULL COMMENT '0=in 1=out 2=break_out 3=break_in 4=ot_in 5=ot_out',
    verify_mode     TINYINT         NULL COMMENT '1=fingerprint 4=card 15=face 25=palm',
    work_code       INT             NULL,
    reserved_fields JSON            NULL COMMENT 'Kolom ke-3+ varian B, dan field tak dikenal lainnya',

    -- Jejak
    record_hash     CHAR(40)        NOT NULL
                    COMMENT 'SHA1(device|pin|punch_at|status|verify|work_code) — kunci anti-duplikat',
    raw_line        VARCHAR(512)    NOT NULL COMMENT 'Baris asli persis seperti dikirim device',
    format_variant  ENUM('positional5','positionalN','keyvalue') NOT NULL,
    parse_status    ENUM('ok','partial','failed') NOT NULL DEFAULT 'ok',
    iclock_request_id BIGINT UNSIGNED NULL COMMENT 'Request asal, untuk penelusuran',
    is_processed    TINYINT(1)      NOT NULL DEFAULT 0
                    COMMENT '1 = sudah dihitung ke laporan kehadiran',
    created_at      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),

    PRIMARY KEY (id),
    UNIQUE KEY uk_attlog_hash (record_hash)
        COMMENT 'Ini yang membuat pengiriman ulang device tidak berbahaya',
    KEY idx_attlog_employee_time (employee_id, punch_at),
    KEY idx_attlog_pin_time (pin, punch_at)
        COMMENT 'Untuk pencarian punch saat PIN belum dipetakan',
    KEY idx_attlog_device_time (device_id, punch_at),
    KEY idx_attlog_date (punch_date),
    KEY idx_attlog_unprocessed (is_processed, punch_at)
        COMMENT 'Untuk worker yang menghitung keterlambatan',
    KEY idx_attlog_request (iclock_request_id),

    CONSTRAINT fk_attlog_device FOREIGN KEY (device_id)
        REFERENCES device (id) ON DELETE SET NULL,
    CONSTRAINT fk_attlog_employee FOREIGN KEY (employee_id)
        REFERENCES employee (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Log absensi mentah dari device';
```

**Catatan desain — bagian paling penting:**

- **`record_hash` adalah kunci ketahanan sistem ini.** Device memang mengirim
  ulang data saat jaringan putus. Karena `UNIQUE`, penyimpanan ulang menjadi
  tidak berbahaya dan kita bisa memakai `INSERT ... ON DUPLICATE KEY UPDATE`
  tanpa perlu mengecek duplikat lebih dulu. Isi hash **tidak memakai `Stamp`**
  dari device, karena perilaku `Stamp` berbeda antar firmware — lebih aman
  memakai isi punch itu sendiri.

- **`punch_at` memakai waktu device, bukan waktu server.** Punch yang tersimpan
  di device saat jaringan mati tidak boleh tercatat di waktu sinkronisasi.

- **`device_id` dan `employee_id` memakai `ON DELETE SET NULL`,** bukan
  `CASCADE`. Menghapus seorang karyawan **tidak boleh** menghapus riwayat
  absensinya. Ini kesalahan yang bisa berakibat serius pada data kehadiran.

- **`serial_number` disimpan langsung** bersama `device_id` supaya jejak asal
  data tetap ada walau baris `device` hilang.

- **`employee_id` boleh `NULL`.** Ini disengaja: PIN yang tidak dikenal tetap
  harus tersimpan supaya bisa dicocokkan belakangan setelah data karyawan
  dilengkapi. Membuang punch tanpa pemilik akan menghilangkan data yang tidak
  bisa diperoleh kembali.

- `raw_line` menyimpan teks asli agar masalah parsing bisa didiagnosis tanpa
  harus membuka `iclock_request`.

---

## 6. Tabel `device_user`

Cerminan data user **seperti yang ada di device**. Bukan sumber kebenaran.

```sql
CREATE TABLE device_user (
    id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    device_id       BIGINT UNSIGNED NOT NULL,
    pin             VARCHAR(24)     NOT NULL,
    name            VARCHAR(128)    NULL COMMENT 'Nama seperti di device',
    privilege       TINYINT         NULL COMMENT '0=user 14=admin',
    card_no         VARCHAR(32)     NULL,
    password        VARCHAR(64)     NULL COMMENT 'Password device; sebaiknya dikosongkan',
    group_id        VARCHAR(16)     NULL,
    sync_status     ENUM('in_sync','device_only','server_only','conflict')
                    NOT NULL DEFAULT 'in_sync'
                    COMMENT 'device_only = ada di device tapi tidak ada di employee',
    last_seen_at    DATETIME        NULL COMMENT 'Terakhir terlihat di USERINFO dari device',
    raw_line        VARCHAR(512)    NULL,
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP
                    ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (id),
    UNIQUE KEY uk_device_user (device_id, pin)
        COMMENT 'Satu PIN hanya boleh muncul sekali per device',
    KEY idx_du_pin (pin),
    KEY idx_du_sync (sync_status),

    CONSTRAINT fk_du_device FOREIGN KEY (device_id)
        REFERENCES device (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='User yang ada di device (mirror, bukan sumber kebenaran)';
```

**Catatan desain:**
- `sync_status='device_only'` menandai user yang ada di mesin tapi tidak
  terdaftar sebagai karyawan. Ini kondisi yang perlu ditinjau admin — sering
  berarti ada orang yang mendaftarkan dirinya sendiri di device.
- `ON DELETE CASCADE` di sini **tepat**, berbeda dengan `attendance_log`: user
  device tidak punya makna bila device-nya sudah tidak ada.
- Kolom `password` sebaiknya dibiarkan kosong; menyimpan password device adalah
  risiko yang tidak sebanding manfaatnya.

---

## 7. Tabel `command_queue`

Antrian perintah server → device. Disimpan di DB, bukan di memori, supaya
server bisa restart tanpa kehilangan perintah.

```sql
CREATE TABLE command_queue (
    id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    command_id      BIGINT UNSIGNED NOT NULL
                    COMMENT 'ID di wire protocol: C:<command_id>:<cmd>. Naik monoton.',
    device_id       BIGINT UNSIGNED NOT NULL,
    command_text    VARCHAR(1024)   NOT NULL COMMENT 'Perintah tanpa prefix C:<id>:',
    command_type    VARCHAR(32)     NOT NULL
                    COMMENT 'INFO/CHECK/DATA_UPDATE_USER/DATA_DELETE_USER/DATA_QUERY_USER/GET_OPTION/LOG/SHELL',
    payload_json    JSON            NULL COMMENT 'Parameter terstruktur sebelum dirakit',
    status          ENUM('pending','sent','acked','failed','cancelled')
                    NOT NULL DEFAULT 'pending',
    attempt_count   TINYINT UNSIGNED NOT NULL DEFAULT 0,
    max_attempts    TINYINT UNSIGNED NOT NULL DEFAULT 3,
    sent_at         DATETIME        NULL COMMENT 'Kapan dikirim ke device',
    acked_at        DATETIME        NULL COMMENT 'Kapan device konfirmasi',
    return_code     INT             NULL COMMENT '0=sukses, -1002=sintaks, -1004=tidak didukung',
    response_raw    VARCHAR(1024)   NULL COMMENT 'Body devicecmd mentah',
    error_message   VARCHAR(255)    NULL,
    requested_by    BIGINT UNSIGNED NULL COMMENT 'User internal yang memicu, NULL = sistem',
    expires_at      DATETIME        NULL COMMENT 'Lewat waktu ini perintah dibatalkan',
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP
                    ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (id),
    UNIQUE KEY uk_cmd_command_id (command_id)
        COMMENT 'Kunci korelasi dengan laporan devicecmd',
    KEY idx_cmd_device_status (device_id, status, created_at)
        COMMENT 'Query utama getrequest: ambil perintah pending device ini',
    KEY idx_cmd_stuck (status, sent_at)
        COMMENT 'Untuk mengembalikan perintah yang tidak pernah dikonfirmasi',
    KEY idx_cmd_type (command_type),

    CONSTRAINT fk_cmd_device FOREIGN KEY (device_id)
        REFERENCES device (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Antrian perintah ke device, dikirim lewat getrequest';
```

**Catatan desain:**
- `command_id` **terpisah** dari `id` tabel. Alasannya: ID di wire protocol harus
  naik monoton dan unik lintas seluruh device (device lama bisa menyimpan ID yang
  belum dikonfirmasi), sedangkan `id` tabel boleh saja berbeda. Memisahkan
  keduanya menghindari tabrakan ID saat baris dihapus atau diarsipkan.
- Siklus status: `pending` → `sent` (saat `getrequest`) → `acked`/`failed`
  (saat `devicecmd`). Bila `sent` melewati 15 menit, kembali ke `pending` dengan
  `attempt_count + 1`; setelah `max_attempts`, jadi `failed`.
- `return_code=-1004` harus memicu penonaktifan kapabilitas di tabel `device`
  agar perintah sejenis tidak dikirim lagi.
- `expires_at` mencegah perintah lama mengejutkan device berhari-hari kemudian —
  misalnya "hapus user" yang sudah tidak relevan.

---

## 8. Tabel opsional — operlog

```sql
CREATE TABLE device_operlog (
    id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    device_id       BIGINT UNSIGNED NULL,
    serial_number   VARCHAR(64)     NOT NULL,
    pin             VARCHAR(24)     NULL,
    log_at          DATETIME        NOT NULL,
    op_type         VARCHAR(32)     NULL,
    value1          VARCHAR(64)     NULL,
    value2          VARCHAR(64)     NULL,
    value3          VARCHAR(64)     NULL,
    record_hash     CHAR(40)        NOT NULL,
    raw_line        VARCHAR(512)    NOT NULL,
    created_at      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),

    PRIMARY KEY (id),
    UNIQUE KEY uk_operlog_hash (record_hash),
    KEY idx_operlog_device_time (device_id, log_at),

    CONSTRAINT fk_operlog_device FOREIGN KEY (device_id)
        REFERENCES device (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Log operasi device (buka pintu, alarm) — bukan absensi';
```

---

## 9. Urutan penerapan (migrasi)

Urutan penting karena foreign key:

```
1. device
2. employee
3. iclock_request      (FK → device, nullable)
4. attendance_log      (FK → device, employee)
5. device_user         (FK → device)
6. command_queue       (FK → device)
7. device_operlog      (FK → device)
```

---

## 10. Contoh kueri penting

### 10.1 Simpan punch, abaikan duplikat (operasi utama ingest)
```sql
INSERT INTO attendance_log
    (device_id, serial_number, pin, punch_at, punch_date,
     status_code, verify_mode, work_code, record_hash, raw_line, format_variant)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON DUPLICATE KEY UPDATE id = id;   -- no-op bila hash sudah ada
```
`affected_rows` bernilai 1 bila baris baru, 0 bila duplikat — dari situ
`stored_count` dan `dup_count` dihitung.

### 10.2 Ambil perintah pending untuk device (respons getrequest)
```sql
SELECT command_id, command_text
FROM command_queue
WHERE device_id = ?
  AND status = 'pending'
  AND (expires_at IS NULL OR expires_at > NOW())
ORDER BY command_id
LIMIT 50;
```

### 10.3 Kembalikan perintah yang macet (job berkala)
```sql
UPDATE command_queue
SET status = CASE WHEN attempt_count + 1 >= max_attempts THEN 'failed' ELSE 'pending' END,
    attempt_count = attempt_count + 1,
    error_message = 'Tidak dikonfirmasi device dalam 15 menit'
WHERE status = 'sent'
  AND sent_at < NOW() - INTERVAL 15 MINUTE;
```

### 10.4 Device yang dianggap offline
```sql
SELECT id, serial_number, display_name, last_seen_at
FROM device
WHERE status = 'active'
  AND (last_seen_at IS NULL
       OR last_seen_at < NOW() - INTERVAL 3 * poll_delay SECOND);
```

### 10.5 Rekap absensi harian per karyawan
```sql
SELECT e.pin, e.name, a.punch_date,
       MIN(a.punch_at) AS first_in,
       MAX(a.punch_at) AS last_out,
       COUNT(*)        AS punch_count
FROM attendance_log a
JOIN employee e ON e.id = a.employee_id
WHERE a.punch_date BETWEEN ? AND ?
GROUP BY e.pin, e.name, a.punch_date
ORDER BY a.punch_date, e.pin;
```

### 10.6 Punch yang belum terpetakan ke karyawan
```sql
SELECT a.pin, COUNT(*) AS total, MIN(a.punch_at) AS pertama, MAX(a.punch_at) AS terakhir
FROM attendance_log a
WHERE a.employee_id IS NULL
GROUP BY a.pin
ORDER BY total DESC;
```

---

## 11. Pemeliharaan

| Tabel | Pertumbuhan | Kebijakan |
|---|---|---|
| `iclock_request` | Sangat cepat | Retensi 30 hari; partisi bulanan; simpan statistik saja |
| `attendance_log` | Cepat (~1000/hari/device) | Permanen; arsipkan per tahun |
| `device_operlog` | Sedang | Retensi 90 hari |
| `command_queue` | Lambat | Hapus baris `acked`/`failed` > 30 hari |
| `device_user` | Statis | Ikut device (CASCADE) |

**Penting:** jangan aktifkan `Realtime=1` bersamaan dengan `TransInterval`
rendah pada banyak device tanpa memantau beban tulis. Beberapa device di satu
lokasi bisa menghasilkan ribuan baris `attendance_log` per jam pada jam sibuk.
