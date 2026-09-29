-- =============================================================================
-- Migrasi 002 — Template sidik jari, sinkronisasi dua arah, & jadwal shift
--
-- Melengkapi 001_init_adms_push.sql berdasarkan keputusan pemangku kepentingan:
--   * Device: ZKTeco X100C (fingerprint only)
--   * Template sidik jari WAJIB ditarik (bukan wajah)
--   * Sinkronisasi user DUA ARAH
--   * Retensi iclock_request 30 hari
--   * Absensi dihubungkan ke jadwal shift
--
-- Jalankan SETELAH 001:
--   mysql -u <user> -p <db> < migrations/002_biometric_sync_schedule.sql
-- =============================================================================

SET NAMES utf8mb4;

-- -----------------------------------------------------------------------------
-- 8. finger_template — template sidik jari (BLOB)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS finger_template (
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
    -- Satu slot jari untuk satu PIN per device (dan satu master per PIN bila device_id NULL)
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

-- -----------------------------------------------------------------------------
-- 9. sync_log — jejak setiap pertukaran data dua arah (server <-> device)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sync_log (
    id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    device_id     BIGINT UNSIGNED NULL,
    serial_number VARCHAR(64)     NOT NULL,
    direction     ENUM('server_to_device','device_to_server') NOT NULL,
    entity_type   ENUM('user','finger_template','card','command') NOT NULL,
    pin           VARCHAR(24)     NULL,
    finger_index  TINYINT UNSIGNED NULL,
    action        ENUM('create','update','delete','query') NOT NULL,
    outcome       ENUM('applied','skipped','conflict','failed') NOT NULL,
    conflict_detail VARCHAR(255)  NULL
                  COMMENT 'Diisi bila outcome=conflict: nilai server vs device',
    resolved_by   ENUM('server_wins','device_wins','manual','none')
                  NOT NULL DEFAULT 'none',
    command_id    BIGINT UNSIGNED NULL COMMENT 'Perintah yang memicunya, bila ada',
    created_at    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),

    PRIMARY KEY (id),
    KEY idx_sync_device_created (device_id, created_at),
    KEY idx_sync_pin (pin, created_at),
    KEY idx_sync_conflict (outcome, created_at)
        COMMENT 'Untuk menampilkan konflik yang perlu ditinjau admin',

    CONSTRAINT fk_sync_device FOREIGN KEY (device_id)
        REFERENCES device (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Jejak sinkronisasi dua arah server <-> device';

-- -----------------------------------------------------------------------------
-- 10. shift & shift_assignment — jadwal kerja untuk hitung keterlambatan
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS shift (
    id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    name              VARCHAR(64)     NOT NULL,
    start_time        TIME            NOT NULL,
    end_time          TIME            NOT NULL
                      COMMENT 'Bila <= start_time, shift melewati tengah malam',
    late_tolerance_min SMALLINT UNSIGNED NOT NULL DEFAULT 0
                      COMMENT 'Toleransi keterlambatan (menit)',
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

CREATE TABLE IF NOT EXISTS shift_assignment (
    id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    employee_id BIGINT UNSIGNED NOT NULL,
    shift_id    BIGINT UNSIGNED NOT NULL,
    effective_from DATE         NOT NULL,
    effective_to   DATE         NULL COMMENT 'NULL = berlaku sampai dicabut',
    work_days   SET('MO','TU','WE','TH','FR','SA','SU') NOT NULL
                DEFAULT 'MO,TU,WE,TH,FR'
                COMMENT 'Hari kerja untuk penugasan ini',
    created_at  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP
                                ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (id),
    UNIQUE KEY uk_assign (employee_id, shift_id, effective_from)
        COMMENT 'Mencegah penugasan ganda untuk tanggal mulai yang sama',
    KEY idx_assign_employee (employee_id, effective_from),
    KEY idx_assign_shift (shift_id),

    CONSTRAINT fk_assign_employee FOREIGN KEY (employee_id)
        REFERENCES employee (id) ON DELETE CASCADE,
    CONSTRAINT fk_assign_shift FOREIGN KEY (shift_id)
        REFERENCES shift (id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Penugasan shift ke karyawan per rentang tanggal';

-- -----------------------------------------------------------------------------
-- 11. daily_attendance — hasil olahan punch menjadi kehadiran harian
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS daily_attendance (
    id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    employee_id     BIGINT UNSIGNED NOT NULL,
    work_date       DATE            NOT NULL,
    shift_id        BIGINT UNSIGNED NULL COMMENT 'Shift yang berlaku hari itu',
    first_in        DATETIME        NULL,
    last_out        DATETIME        NULL,
    punch_count     SMALLINT UNSIGNED NOT NULL DEFAULT 0,
    late_minutes    INT             NOT NULL DEFAULT 0
                    COMMENT 'Keterlambatan bersih setelah toleransi shift',
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
    UNIQUE KEY uk_daily (employee_id, work_date)
        COMMENT 'Satu baris kehadiran per karyawan per hari',
    KEY idx_daily_date (work_date),
    KEY idx_daily_status (status, work_date),
    KEY idx_daily_shift (shift_id),

    CONSTRAINT fk_daily_employee FOREIGN KEY (employee_id)
        REFERENCES employee (id) ON DELETE CASCADE,
    CONSTRAINT fk_daily_shift FOREIGN KEY (shift_id)
        REFERENCES shift (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Ringkasan kehadiran harian (hasil olahan attendance_log)';

-- -----------------------------------------------------------------------------
-- 12. holiday — hari libur, agar absen tidak dihitung alpa
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS holiday (
    id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    holiday_date DATE           NOT NULL,
    name        VARCHAR(128)    NOT NULL,
    is_recurring TINYINT(1)     NOT NULL DEFAULT 0 COMMENT '1 = berulang tiap tahun',
    created_at  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (id),
    UNIQUE KEY uk_holiday (holiday_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Hari libur';

-- =============================================================================
-- Selesai. Urutan setelah migrasi 001.
-- =============================================================================
