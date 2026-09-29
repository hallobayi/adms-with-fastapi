# Skema Database — ADMS ZKTeco Push

**DBMS:** MySQL 8.0+ (InnoDB, `utf8mb4`)
**Engine:** semua tabel InnoDB
**Device target:** ZKTeco **X100C** (fingerprint only)
**Migrasi:**
- `migrations/001_init_adms_push.sql` — inti protokol push (7 tabel)
- `migrations/002_biometric_sync_schedule.sql` — biometrik, sync 2 arah, shift (6 tabel)

---

## 0. Keputusan pemangku kepentingan

| # | Keputusan | Konsekuensi pada skema |
|---|---|---|
| 1 | Device = **X100C** | Fingerprint saja; tidak ada tabel face/photo. `TransFlag` tetap `1111000000`. |
| 2 | Tarik **hanya sidik jari** (bukan wajah) | Tambah `finger_template` dengan `MEDIUMBLOB`. Tidak ada `face_template`/`biophoto`. |
| 3 | **Sinkronisasi dua arah** | Tambah `version` + `sync_state` di `finger_template`, dan tabel `sync_log` untuk jejak + resolusi konflik. |
| 4 | Retensi `iclock_request` = **30 hari** | Kebijakan pembersihan + pemadatan `body_raw` (lihat §13). |
| 5 | Absensi **dihubungkan ke jadwal shift** | Tambah `shift`, `shift_assignment`, `daily_attendance`, `holiday`. |

### 0.1 Catatan penting tentang X100C

**ADMS adalah fungsi OPSIONAL pada X100C.** Dari lembar spesifikasi: fitur
standar mencakup SMS, Workcode, DST, Scheduled-bell; sedangkan **ADMS dan
Webserver masuk daftar "Optional Functions"**. Artinya:

> **Sebelum implementasi dimulai, pastikan firmware X100C yang dipakai sudah
> mendukung dan mengaktifkan PUSH/ADMS.** Bila belum, device tidak akan pernah
> memanggil server, dan seluruh pekerjaan integrasi tidak bisa diuji. Beberapa
> unit perlu upgrade firmware terlebih dahulu (via USB), lalu fitur PUSH
> diaktifkan.

Ini risiko paling awal dan paling menentukan pada proyek ini — bukan hal yang
bisa diabaikan sampai fase akhir.

Spesifikasi X100C yang relevan:

| Item | Nilai |
|---|---|
| Kapasitas sidik jari | 3.200 |
| Kapasitas kartu | ID dan IC (opsional) |
| Kapasitas log | 100.000 (120.000 di tabel lain) |
| Komunikasi | TCP/IP, USB host/client (opsional) |
| Zona waktu | Perlu diperhatikan; `TimeZone=7` dipakai referensi untuk WIB |
| Verifikasi | Fingerprint, PIN, kartu RFID opsional |

Karena kapasitas log **100.000 record**, perhatikan kebijakan `ResLogCount`
dan pengambilan log berkala — bila penuh sebelum tersinkron, punch lama bisa
terhapus di device dan hilang permanen.

---

## 1. Peta tabel

```
                           ┌──────────────────┐
                           │      device      │ 1 device = 1 mesin X100C
                           │ (SN, token,      │
                           │  delay, opt)     │
                           └────────┬─────────┘
                                    │
   ┌────────────┬───────────────┬───┴────────┬────────────────┬─────────────┐
   │            │               │            │                │             │
   ▼            ▼               ▼            ▼                ▼             ▼
┌──────────┐ ┌──────────────┐ ┌──────────┐ ┌──────────┐ ┌───────────┐ ┌──────────┐
│iclock_   │ │attendance_log│ │command_  │ │device_   │ │finger_    │ │device_   │
│request   │ │ (punch)      │ │queue     │ │user      │ │template   │ │operlog   │
│body mntah│ │ UNIQUE hash  │ │C:<id>:cmd│ │(mirror)  │ │(BLOB)     │ │          │
└──────────┘ └──────┬───────┘ └──────────┘ └──────────┘ └─────┬─────┘ └──────────┘
                    │                                          │
                    ▼                                          │
          ┌──────────────────┐                                 │
          │    employee      │◄────────────────────────────────┘
          │ (pin, nama)      │  sumber kebenaran
          └───┬──────────┬───┘
              │          │
              ▼          ▼
   ┌────────────────┐  ┌──────────────────┐
   │shift_assignment│→ │      shift       │  jadwal kerja
   └────────────────┘  └──────────────────┘
              │
              ▼
   ┌────────────────────┐        ┌───────────┐
   │  daily_attendance  │        │  sync_log │  jejak sync 2 arah
   │  (hasil olahan)    │        └───────────┘
   └────────────────────┘
```

**Alur data:** `iclock_request` menyimpan **setiap** request apa adanya →
parser menulis ke `attendance_log` / `device_user` / `finger_template`.
Tabel mentah inilah yang membuat kita bisa memperbaiki parser lalu memproses
ulang data lama. `attendance_log` kemudian diolah oleh job terjadwal menjadi
`daily_attendance` dengan bantuan `shift_assignment`.

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

## 8b. Tabel `finger_template` — template sidik jari

Ini tabel yang memenuhi keputusan "HANYA FINGER". Tanpa ini, sinkronisasi dua
arah tidak mungkin: device tidak bisa memverifikasi sidik jari yang belum
dikirim kepadanya.

> **Catatan format:** Model X100C **tidak dikonfirmasi** memakai header 6 byte
> ZKTeco klasik (`size`/`uid`/`finger_id`/`flag`). Referensi implementasi yang
> diuji di X100-C hanya mencatat body mentah tanpa menguraikannya. Karena itu
> skema ini menyimpan blob apa adanya dan memperlakukannya sebagai data buram
> — lihat §8b.1.

```sql
CREATE TABLE finger_template (
    id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    employee_id   BIGINT UNSIGNED NULL COMMENT 'NULL bila PIN belum dipetakan',
    device_id     BIGINT UNSIGNED NULL
                  COMMENT 'NULL = template master (milik server), bukan salinan device',
    pin           VARCHAR(24)     NOT NULL,
    finger_index  TINYINT UNSIGNED NOT NULL COMMENT 'Slot jari 0-9',
    template_data MEDIUMBLOB      NOT NULL COMMENT 'Blob template mentah dari device',
    template_size INT UNSIGNED    NOT NULL COMMENT 'Ukuran menurut header 2 byte pertama',
    version       INT UNSIGNED    NOT NULL DEFAULT 1
                  COMMENT 'Naik setiap template berubah; dipakai resolusi konflik',
    quality_score TINYINT UNSIGNED NULL COMMENT 'Perkiraan kualitas dari heuristik byte',
    is_valid      TINYINT(1)      NOT NULL DEFAULT 1,
    source        ENUM('device','server_import') NOT NULL DEFAULT 'device',
    sync_state    ENUM('in_sync','pending_push','pending_pull','conflict','failed')
                  NOT NULL DEFAULT 'in_sync',
    last_pushed_at DATETIME       NULL COMMENT 'Terakhir dikirim ke device',
    last_pulled_at DATETIME       NULL COMMENT 'Terakhir ditarik dari device',
    created_at    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP
                                  ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (id),
    UNIQUE KEY uk_finger_slot (pin, finger_index, device_id),
    KEY idx_finger_employee (employee_id),
    KEY idx_finger_device (device_id),
    KEY idx_finger_sync (sync_state),

    CONSTRAINT fk_finger_employee FOREIGN KEY (employee_id)
        REFERENCES employee (id) ON DELETE SET NULL,
    CONSTRAINT fk_finger_device FOREIGN KEY (device_id)
        REFERENCES device (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Template sidik jari per PIN dan slot jari';
```

### 8b.1 Mengapa menyimpan blob mentah

Template sidik jari ZKTeco adalah **format binary rahasia** yang tidak
didokumentasikan resmi dan berbeda antar keluarga firmware. Menguraikannya
berdasarkan dugaan adalah cara paling cepat menghasilkan data rusak yang tidak
bisa dipulihkan.

Karena itu:
- `template_data` menyimpan **byte persis** seperti yang dikirim device.
- `template_size` dan `quality_score` bersifat **informasional** — berguna untuk
  memantau, **bukan** untuk memutuskan validitas.
- **Jangan pernah** memotong, mengubah, atau "menormalkan" blob ini.

**Verifikasi wajib sebelum mengandalkan isi template:** tarik template dari
device, kirim ulang persis apa adanya, lalu pastikan user bisa verifikasi
sidik jari di device. Bila berhasil, format blob sudah benar — tanpa perlu tahu
strukturnya.

### 8b.2 Mengapa ada `device_id` yang boleh NULL

- `device_id = NULL` → **template master**, dimiliki server. Ini "sumber
  kebenaran" yang dipakai untuk mendorong ke device mana pun.
- `device_id = <id>` → **salinan** di device tertentu.

Pemisahan ini penting untuk sinkronisasi dua arah: bila device A mengirim
template baru, ia disimpan sebagai master (`device_id NULL`, `version + 1`),
lalu disebarkan ke semua device lain sebagai baris salinan. Tanpa pemisahan
ini, kita tidak bisa membedakan "template ini berasal dari device mana".

### 8b.3 Siklus `sync_state`

| State | Arti |
|---|---|
| `in_sync` | Server dan device sepakat |
| `pending_push` | Master berubah, menunggu dikirim ke device |
| `pending_pull` | Device melaporkan ada, menunggu ditarik |
| `conflict` | Ada versi berbeda dan tidak bisa diputuskan otomatis |
| `failed` | Pengiriman/penarikan gagal berulang |

`version` naik setiap template berubah. Saat membandingkan, **versi lebih
tinggi menang**; bila versi sama tapi isi berbeda → `conflict` + catat di
`sync_log` untuk ditinjau admin.

---

## 8c. Tabel `sync_log` — jejak sinkronisasi dua arah

```sql
CREATE TABLE sync_log (
    id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    device_id     BIGINT UNSIGNED NULL,
    serial_number VARCHAR(64)     NOT NULL,
    direction     ENUM('server_to_device','device_to_server') NOT NULL,
    entity_type   ENUM('user','finger_template','card','command') NOT NULL,
    pin           VARCHAR(24)     NULL,
    finger_index  TINYINT UNSIGNED NULL,
    action        ENUM('create','update','delete','query') NOT NULL,
    outcome       ENUM('applied','skipped','conflict','failed') NOT NULL,
    conflict_detail VARCHAR(255)  NULL,
    resolved_by   ENUM('server_wins','device_wins','manual','none')
                  NOT NULL DEFAULT 'none',
    command_id    BIGINT UNSIGNED NULL,
    created_at    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),

    PRIMARY KEY (id),
    KEY idx_sync_device_created (device_id, created_at),
    KEY idx_sync_pin (pin, created_at),
    KEY idx_sync_conflict (outcome, created_at),

    CONSTRAINT fk_sync_device FOREIGN KEY (device_id)
        REFERENCES device (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Jejak sinkronisasi dua arah server <-> device';
```

**Catatan desain:** dengan 3.200 slot sidik jari per device dan banyak device,
sinkronisasi dua arah bisa membanjiri tabel ini. **Jangan** mencatat setiap
`skipped`; hanya catat `applied`, `conflict`, dan `failed`. `skipped` yang
normal (mis. "sudah sinkron") cukup dihitung di metrik.

---

## 8d–8g. Tabel jadwal shift & kehadiran harian

Lihat `migrations/002_biometric_sync_schedule.sql` untuk definisi lengkap
`shift`, `shift_assignment`, `daily_attendance`, dan `holiday`.

### 8d. `shift`

```sql
CREATE TABLE shift (
    id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    name              VARCHAR(64)     NOT NULL,
    start_time        TIME            NOT NULL,
    end_time          TIME            NOT NULL
                      COMMENT 'Bila <= start_time, shift melewati tengah malam',
    late_tolerance_min SMALLINT UNSIGNED NOT NULL DEFAULT 0,
    early_leave_tol_min SMALLINT UNSIGNED NOT NULL DEFAULT 0,
    is_overnight      TINYINT(1)      NOT NULL DEFAULT 0,
    is_active         TINYINT(1)      NOT NULL DEFAULT 1,
    created_at        DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at        DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP
                                      ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (id),
    UNIQUE KEY uk_shift_name (name),
    KEY idx_shift_active (is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Definisi shift kerja';
```

**Catatan desain — shift lewat tengah malam.** Shift malam (`22:00`–`06:00`)
adalah tempat kesalahan paling umum terjadi. Aturan yang dipakai:
`is_overnight = 1` bila `end_time <= start_time`. Saat mencocokkan punch ke
shift, punch yang jatuh **setelah tengah malam** harus dipetakan ke
`work_date` **hari sebelumnya**, bukan hari kalendernya. Tanpa ini, shift
malam akan terlihat sebagai "alpa" setiap hari.

Disarankan juga menyimpan `late_tolerance_min` **per shift**, bukan global —
toleransi untuk shift malam biasanya berbeda dengan shift pagi.

### 8e. `shift_assignment`

```sql
CREATE TABLE shift_assignment (
    id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    employee_id BIGINT UNSIGNED NOT NULL,
    shift_id    BIGINT UNSIGNED NOT NULL,
    effective_from DATE         NOT NULL,
    effective_to   DATE         NULL COMMENT 'NULL = berlaku sampai dicabut',
    work_days   SET('MO','TU','WE','TH','FR','SA','SU') NOT NULL
                DEFAULT 'MO,TU,WE,TH,FR',
    created_at  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP
                                ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (id),
    UNIQUE KEY uk_assign (employee_id, shift_id, effective_from),
    KEY idx_assign_employee (employee_id, effective_from),
    KEY idx_assign_shift (shift_id),

    CONSTRAINT fk_assign_employee FOREIGN KEY (employee_id)
        REFERENCES employee (id) ON DELETE CASCADE,
    CONSTRAINT fk_assign_shift FOREIGN KEY (shift_id)
        REFERENCES shift (id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Penugasan shift ke karyawan per rentang tanggal';
```

**Catatan desain:** `ON DELETE RESTRICT` pada `shift_id` **disengaja** —
menghapus shift yang masih dipakai penugasan akan membuat perhitungan
keterlambatan kehilangan acuan. Admin harus mencabut penugasan dulu. Sudah
diuji: penghapusan ditolak dengan `ERROR 1451`.

### 8f. `daily_attendance`

```sql
CREATE TABLE daily_attendance (
    id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    employee_id     BIGINT UNSIGNED NOT NULL,
    work_date       DATE            NOT NULL,
    shift_id        BIGINT UNSIGNED NULL,
    first_in        DATETIME        NULL,
    last_out        DATETIME        NULL,
    punch_count     SMALLINT UNSIGNED NOT NULL DEFAULT 0,
    late_minutes    INT             NOT NULL DEFAULT 0,
    early_leave_minutes INT         NOT NULL DEFAULT 0,
    overtime_minutes INT            NOT NULL DEFAULT 0,
    worked_minutes  INT             NULL COMMENT 'NULL bila punch tidak lengkap',
    status          ENUM('present','late','absent','incomplete','holiday','leave')
                    NOT NULL DEFAULT 'present',
    is_manual       TINYINT(1)      NOT NULL DEFAULT 0
                    COMMENT '1 = dikoreksi manual, jangan ditimpa job otomatis',
    note            VARCHAR(255)    NULL,
    computed_at     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP
                                    ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (id),
    UNIQUE KEY uk_daily (employee_id, work_date),
    KEY idx_daily_date (work_date),
    KEY idx_daily_status (status, work_date),
    KEY idx_daily_shift (shift_id),

    CONSTRAINT fk_daily_employee FOREIGN KEY (employee_id)
        REFERENCES employee (id) ON DELETE CASCADE,
    CONSTRAINT fk_daily_shift FOREIGN KEY (shift_id)
        REFERENCES shift (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Ringkasan kehadiran harian';
```

**Catatan desain:**
- `status='incomplete'` penting. Punch yang hanya berisi satu sisi (masuk saja
  tanpa keluar) **tidak boleh** diperlakukan sebagai "hadir penuh" maupun
  "alpa" — keduanya salah dan akan memicu keluhan. Tandai sebagai tidak
  lengkap dan minta koreksi.
- `is_manual` melindungi koreksi admin dari ditimpa job otomatis. Setiap job
  hitung ulang **wajib** menambahkan `AND is_manual = 0`.
- `daily_attendance` adalah **turunan**, bukan sumber kebenaran.
  `attendance_log` tetap aslinya, dan tabel ini bisa dihitung ulang kapan saja.

### 8g. `holiday`

```sql
CREATE TABLE holiday (
    id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    holiday_date DATE           NOT NULL,
    name        VARCHAR(128)    NOT NULL,
    is_recurring TINYINT(1)     NOT NULL DEFAULT 0,
    created_at  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (id),
    UNIQUE KEY uk_holiday (holiday_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Hari libur';
```

Tanpa tabel ini, job harian akan menandai seluruh karyawan **alpa** di hari
libur nasional. Ini bug yang sangat terlihat dan mudah dicegah.

---

## 9. Urutan penerapan (migrasi)

Urutan penting karena foreign key:

**Migrasi 001** (`001_init_adms_push.sql`):
```
1. device
2. employee
3. iclock_request      (FK → device, nullable)
4. attendance_log      (FK → device, employee)
5. device_user         (FK → device)
6. command_queue       (FK → device)
7. device_operlog      (FK → device)
```

**Migrasi 002** (`002_biometric_sync_schedule.sql`):
```
8.  finger_template      (FK → employee, device)
9.  sync_log             (FK → device)
10. shift
11. shift_assignment     (FK → employee, shift)
12. daily_attendance     (FK → employee, shift)
13. holiday
```

Jalankan berurutan:
```bash
mysql -u <user> -p <db> < migrations/001_init_adms_push.sql
mysql -u <user> -p <db> < migrations/002_biometric_sync_schedule.sql
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
| `iclock_request` | Sangat cepat | **Retensi 30 hari** (lihat §12) |
| `attendance_log` | Cepat (~1000/hari/device) | Permanen; arsipkan per tahun |
| `device_operlog` | Sedang | Retensi 90 hari |
| `command_queue` | Lambat | Hapus baris `acked`/`failed` > 30 hari |
| `device_user` | Statis | Ikut device (CASCADE) |
| `finger_template` | Statis (~3.200 blob/device) | Perkirakan **~30–60 MB/device**; lihat §12 |
| `sync_log` | Cepat | Hanya catat `applied`/`conflict`/`failed`; retensi 90 hari |
| `daily_attendance` | Terkendali (1 baris/karyawan/hari) | Permanen; bisa dihitung ulang |

**Penting:** jangan aktifkan `Realtime=1` bersamaan dengan `TransInterval`
rendah pada banyak device tanpa memantau beban tulis. Beberapa device di satu
lokasi bisa menghasilkan ribuan baris `attendance_log` per jam pada jam sibuk.

**Penting (X100C):** kapasitas log device hanya **100.000 record**. Bila
penuh sebelum tersinkron, punch lama **terhapus di device dan hilang
permanen** — tidak ada cara menariknya kembali. Pastikan pengambilan log
berjalan jauh sebelum batas itu tercapai, dan pantau `AttLogCount` dari
`GET OPTION`.

---

## 12. Kebijakan pemeliharaan detail

### 12.1 Retensi `iclock_request` = 30 hari

Bila `iclock_request` tumbuh paling cepat, jangan sekadar `DELETE` — pindahkan
statistiknya dulu, lalu hapus `body_raw` (yang menjadi biaya terbesar).

```sql
-- Tahap 1: padatkan body mentah untuk request lama, pertahankan statistiknya.
-- Semua informasi yang berguna untuk diagnosis sudah ada di kolom lain
-- (counts, process_status, error_message).
UPDATE iclock_request
SET body_raw = NULL
WHERE body_raw IS NOT NULL
  AND created_at < NOW() - INTERVAL 7 DAY
  AND process_status <> 'failed'
  AND table_name <> 'USERINFO';   -- USERINFO perlu utuh untuk pemrosesan ulang

-- Tahap 2: hapus dari DB, tapi simpan jalur arsip untuk yang gagal.
-- Semua request yang GAGAL harus sudah diarsipkan ke storage terlebih dahulu,
-- karena inilah baris yang nanti perlu diproses ulang setelah parser diperbaiki.
DELETE FROM iclock_request
WHERE created_at < NOW() - INTERVAL 30 DAY
  AND process_status <> 'failed';

-- Tahap 3: request gagal diarsipkan setelah 90 hari.
DELETE FROM iclock_request
WHERE created_at < NOW() - INTERVAL 90 DAY;
```

**Aturan penting:** baris dengan `process_status='failed'` **tidak boleh**
dihapus pada pembersihan 30 hari. Tujuannya agar data yang gagal diparse tetap
bisa dipulihkan setelah parser diperbaiki. Arsipkan `body_raw`-nya ke file
(minio/disk) sebelum dihapus, lalu simpan lokasinya di `error_message`.

Jalankan sebagai job harian di luar jam sibuk, dengan `LIMIT` per batch
(mis. 5.000 baris) untuk menghindari tabel lock panjang:

```sql
DELETE FROM iclock_request
WHERE created_at < NOW() - INTERVAL 30 DAY
  AND process_status <> 'failed'
ORDER BY id
LIMIT 5000;
```

### 12.2 Kebutuhan penyimpanan sidik jari

Perkiraan kasar (verifikasi dengan menakar blob nyata dari device sebelum
finalisasi kapasitas):

```
per device = jumlah_user × template_per_user × ukuran_template
           = 500 user × 2 jari × ~2–5 KB
           = ~2–5 MB per device (tanpa overhead InnoDB)
```

InnoDB menambah overhead; perkirakan **~2× ukuran data mentah**. Untuk 3.200
slot penuh (kapasitas maksimum X100C), siapkan **~30–60 MB per device**.

**Catatan penting:** template sidik jari adalah **data biometrik pribadi**.
Perlakukan sebagai data sensitif:
- Batasi akses ke tabel ini (jangan tampilkan di API umum).
- Jangan pernah mengirim blob ke client browser.
- Audit unduhan template.
- Pertimbangkan enkripsi at-rest di level tabel/kolom.
- Pastikan ada dasar hukum/consent dari karyawan sesuai regulasi setempat (PDP).

---

## 13. Alur sinkronisasi dua arah

Ini yang perlu dipahami saat mengimplementasikan keputusan "YA, dua arah".

### 13.1 Aturan penyelesaian konflik

| Kondisi | Tindakan |
|---|---|
| Hanya ada di server | Push ke device (`pending_push`) |
| Hanya ada di device | Tarik ke server sebagai master (`pending_pull`) |
| Keduanya ada, `version` server > device | Push ke device |
| Keduanya ada, `version` device > server | Tarik dari device, jadikan master |
| `version` sama, isi **sama** | `in_sync` — tidak ada aksi |
| `version` sama, isi **berbeda** | `conflict` → catat di `sync_log`, tunggu admin |

**Aturan emas: jangan pernah menimpa data sidik jari secara diam-diam.**
Template sidik jari sulit direproduksi (karyawan harus datang dan merekam
ulang). Bila ragu, tandai `conflict` dan minta keputusan manusia — itu jauh
lebih murah daripada menghapus sidik jari orang.

### 13.2 Bentuk `sync_log` aman yang mencegah banjir log

```sql
-- Catat hasil sinkronisasi. Lihat §8c: JANGAN catat 'skipped' yang normal.
INSERT INTO sync_log
    (device_id, serial_number, direction, entity_type, pin, finger_index,
     action, outcome, conflict_detail, resolved_by)
SELECT ?, ?, 'device_to_server', 'finger_template', ?, ?, 'update', 'conflict',
       'server v3 | device v3 (isi berbeda)', 'manual';
```

Query untuk menampilkan konflik yang menunggu keputusan admin:

```sql
SELECT pin, finger_index, conflict_detail, created_at
FROM sync_log
WHERE outcome = 'conflict' AND resolved_by = 'none'
ORDER BY created_at DESC;
```

---

## 14. Alur perhitungan keterlambatan

`daily_attendance` diisi job terjadwal (mis. tiap 15 menit untuk hari berjalan,
plus sekali di akhir hari), **bukan** saat punch masuk — supaya satu punch
tidak memicu perhitungan ulang seluruh hari.

### 14.1 Prinsip

1. Ambil punch dari `attendance_log` untuk `(employee_id, work_date)`.
2. Tentukan shift yang berlaku dari `shift_assignment` (lihat §14.2).
3. `first_in` = punch paling awal, `last_out` = paling akhir.
4. `late_minutes` = selisih `first_in` terhadap `start_time` shift, dikurangi
   `late_tolerance_min`, dan **tidak boleh negatif** (0 berarti tidak telat).
5. Bila karyawan tidak masuk sama sekali → `absent`, **kecuali** tanggal itu
   hari libur (`holiday`) atau bukan hari kerja (`work_days`) atau ada izin → `holiday`/`leave`.
6. Bila hanya ada satu sisi punch → `incomplete`, **jangan** `absent`.

### 14.2 Mencari shift yang berlaku pada suatu tanggal

```sql
SELECT s.id AS shift_id, s.name, s.start_time, s.end_time,
       s.late_tolerance_min, s.is_overnight
FROM shift_assignment sa
JOIN shift s ON s.id = sa.shift_id
WHERE sa.employee_id = ?
  AND ? BETWEEN sa.effective_from
            AND COALESCE(sa.effective_to, '9999-12-31')
  AND s.is_active = 1
ORDER BY sa.effective_from DESC
LIMIT 1;
```

### 14.3 Upsert ke `daily_attendance` (jangan timpa koreksi manual)

```sql
INSERT INTO daily_attendance
    (employee_id, work_date, shift_id, first_in, last_out,
     punch_count, late_minutes, status)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
ON DUPLICATE KEY UPDATE
    first_in       = IF(is_manual = 1, first_in,  VALUES(first_in)),
    last_out       = IF(is_manual = 1, last_out,  VALUES(last_out)),
    punch_count    = IF(is_manual = 1, punch_count, VALUES(punch_count)),
    late_minutes   = IF(is_manual = 1, late_minutes, VALUES(late_minutes)),
    status         = IF(is_manual = 1, status, VALUES(status)),
    shift_id       = IF(is_manual = 1, shift_id, VALUES(shift_id)),
    updated_at     = NOW();
```

Pola `IF(is_manual = 1, kolom_lama, nilai_baru)` memastikan koreksi admin
**tidak pernah** ditimpa job otomatis. Ini penting: tanpa itu, koreksi manual
akan hilang setiap kali job berjalan.

### 14.4 Punch setelah tengah malam pada shift malam

Untuk shift dengan `is_overnight = 1`, punch yang jatuh **setelah tengah malam
dan sebelum/sama dengan `end_time`** harus dipetakan ke `work_date` **hari
sebelumnya**.

**Perhatikan operatornya: `<=`, bukan `<`.** Dengan `<`, punch tepat pada jam
`end_time` (mis. keluar 06:00:00) akan salah tetap di hari kalendernya —
kesalahan yang sangat mudah terjadi dan sulit terlihat.

```sql
SELECT a.*,
       CASE
         WHEN s.is_overnight = 1
              AND HOUR(a.punch_at) <= HOUR(s.end_time)   -- '<=' penting
           THEN DATE(a.punch_at) - INTERVAL 1 DAY
         ELSE a.punch_date
       END AS effective_work_date
FROM attendance_log a
JOIN shift_assignment sa
  ON sa.employee_id = a.employee_id
 AND DATE(a.punch_at) BETWEEN sa.effective_from
                          AND COALESCE(sa.effective_to, '9999-12-31')
JOIN shift s ON s.id = sa.shift_id;
```

**Saran:** jangan andalkan ambang jam saja. Ambang yang lebih kuat adalah
membandingkan punch dengan batas **`start_time` shift** — punch yang terjadi
lebih dari beberapa jam *sebelum* `start_time` (mis. sebelum pukul 18:00 untuk
shift 22:00) hampir pasti milik shift malam **sebelumnya**, sedangkan punch
setelah `start_time` milik shift hari itu. Ini lebih tahan terhadap shift yang
tidak bulat jamnya.

Bila aturan ini terlewat, shift malam akan tampak "alpa" setiap hari — bug
yang sangat terlihat dan sering terjadi.

### 14.5 Menghitung keterlambatan tanpa error underflow

**Jebakan MySQL yang wajib dihindari.** `TIMESTAMPDIFF()` mengembalikan
**BIGINT UNSIGNED**. Bila hasilnya dikurangi (mis. toleransi) dan menjadi
negatif, MySQL melempar:

```
ERROR 1690 (22003): BIGINT UNSIGNED value is out of range
```

Artinya, query yang tampak benar akan **gagal total untuk setiap karyawan yang
datang lebih awal**. Jangan pernah menulis `GREATEST(0, timestampdiff(...) - toleransi)`.

**Cara yang benar — balik urutannya, lalu kurangi:**

```sql
-- late_minutes: keterlambatan setelah toleransi, tidak pernah negatif
SELECT
  CASE
    WHEN a.first_in > ts.scheduled_start
      THEN GREATEST(0,
             TIMESTAMPDIFF(MINUTE, ts.scheduled_start, a.first_in)
             - s.late_tolerance_min)
    ELSE 0
  END AS late_minutes
FROM ...
```

Kunci pemecahannya: **pastikan hanya dihitung saat benar-benar terlambat**
(`first_in > scheduled_start`). Setelah syarat itu benar, selisihnya sudah
pasti non-negatif, sehingga pengurangan toleransi tidak lagi underflow.
Cabang `ELSE 0` menangani kasus datang lebih awal.

Bila tetap ingin memakai `GREATEST`, ubah tipenya lebih dahulu:

```sql
GREATEST(0, CAST(TIMESTAMPDIFF(MINUTE, start, actual) AS SIGNED) - tolerance)
```

Pola yang sama berlaku untuk `early_leave_minutes`.

#### Menggabungkan tanggal dan jam shift menjadi satu titik waktu

`start_time` shift adalah `TIME`, sedangkan punch adalah `DATETIME`. Untuk
membandingkannya, rakit dulu menjadi `DATETIME` — dan ingat shift malam:

```sql
-- Untuk shift biasa: tanggal kerja + jam mulai
TIMESTAMP(da.work_date, s.start_time)

-- Untuk shift malam: titik mulai ada di hari kerja itu,
-- titik selesai ada di hari BERIKUTNYA
TIMESTAMP(da.work_date, s.start_time)                          AS scheduled_start
TIMESTAMP(da.work_date + INTERVAL 1 DAY, s.end_time)           AS scheduled_end
```

Melewatkan `+ INTERVAL 1 DAY` pada `scheduled_end` akan membuat semua shift
malam terlihat "pulang sangat awal" (bahkan negatif), yang lalu memicu bug
underflow di §14.5.

---

## 15. Alur setup device X100C

Ringkasan langkah yang perlu dilakukan di device (dari dokumentasi ZKTeco):

**Prasyarat:** firmware X100C harus sudah punya fitur **PUSH/ADMS**. Bila
belum, upgrade firmware via USB terlebih dahulu.

Di device:

```
Menu > Comm > Cloud Server setting
    Server Address : <IP atau domain server ADMS>
    Server Port    : <port ADMS>
```

Pastikan juga:

```
Menu > Comm > Ethernet
    IP Address / Subnet Mask / Gateway / DNS  → sesuai jaringan server
```

Setelah tersimpan, device akan memanggil `GET /iclock/cdata?SN=<SN>` dalam
waktu beberapa detik hingga satu menit. Device muncul di tabel `device`
dengan `status='pending'` sampai admin menyetujuinya.

**Uji cepat bahwa server sudah dijangkau device:** cek baris baru di
`iclock_request` dengan `endpoint='cdata'`. Bila tabel itu tetap kosong,
masalahnya ada di jaringan/firmware device, **bukan** di kode server.

---
