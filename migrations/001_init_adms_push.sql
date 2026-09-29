-- =============================================================================
-- Migrasi 001 — Skema ZKTeco iClock / ADMS Push Protocol
--
-- Urutan pembuatan penting karena foreign key.
-- Jalankan:  mysql -u <user> -p <db> < migrations/001_init_adms_push.sql
-- =============================================================================

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 1;

-- -----------------------------------------------------------------------------
-- 1. device — device ZKTeco yang terhubung
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS device (
    id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    serial_number     VARCHAR(64)     NOT NULL COMMENT 'SN dari device (query param SN)',
    token_hash        CHAR(64)        NULL COMMENT 'SHA-256 token push; NULL = belum disetujui',
    display_name      VARCHAR(128)    NULL,
    location          VARCHAR(191)    NULL,
    status            ENUM('pending','active','suspended') NOT NULL DEFAULT 'pending',
    model             VARCHAR(64)     NULL,
    firmware          VARCHAR(64)     NULL,
    device_type       VARCHAR(32)     NULL,
    ip_address        VARCHAR(45)     NULL,
    mac_address       VARCHAR(32)     NULL,

    poll_delay        INT UNSIGNED    NOT NULL DEFAULT 30 COMMENT 'Delay= handshake (detik)',
    error_delay       INT UNSIGNED    NOT NULL DEFAULT 60 COMMENT 'ErrorDelay=',
    trans_flag        CHAR(10)        NOT NULL DEFAULT '1111000000' COMMENT 'TransFlag=',
    realtime          TINYINT(1)      NOT NULL DEFAULT 1 COMMENT 'Realtime=',
    stamp_version     INT UNSIGNED    NOT NULL DEFAULT 9999 COMMENT 'Stamp=',

    supports_userinfo TINYINT(1)      NOT NULL DEFAULT 1,
    supports_operlog  TINYINT(1)      NOT NULL DEFAULT 1,
    supports_shell    TINYINT(1)      NOT NULL DEFAULT 0,

    options_json      JSON            NULL,
    last_seen_at      DATETIME        NULL,
    last_handshake_at DATETIME        NULL,
    last_attlog_at    DATETIME        NULL,
    created_at        DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at        DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP
                                      ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (id),
    UNIQUE KEY uk_device_sn (serial_number),
    KEY idx_device_status (status),
    KEY idx_device_last_seen (last_seen_at),
    KEY idx_device_token (token_hash)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Device ZKTeco yang terhubung ke server';

-- -----------------------------------------------------------------------------
-- 2. employee — data karyawan internal (sumber kebenaran)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS employee (
    id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    pin           VARCHAR(24)     NOT NULL COMMENT 'PIN di device',
    name          VARCHAR(128)    NOT NULL,
    employee_code VARCHAR(32)     NULL,
    department    VARCHAR(64)     NULL,
    position      VARCHAR(64)     NULL,
    email         VARCHAR(128)    NULL,
    phone         VARCHAR(32)     NULL,
    joined_at     DATE            NULL,
    resigned_at   DATE            NULL,
    is_active     TINYINT(1)      NOT NULL DEFAULT 1,
    created_at    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP
                                  ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (id),
    UNIQUE KEY uk_employee_pin (pin),
    UNIQUE KEY uk_employee_code (employee_code),
    KEY idx_employee_active (is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Data karyawan internal';

-- -----------------------------------------------------------------------------
-- 3. iclock_request — arsip mentah seluruh request /iclock/*
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS iclock_request (
    id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    device_id       BIGINT UNSIGNED NULL,
    serial_number   VARCHAR(64)     NOT NULL,
    endpoint        VARCHAR(32)     NOT NULL,
    http_method     VARCHAR(8)      NOT NULL,
    table_name      VARCHAR(32)     NULL,
    c_param         VARCHAR(32)     NULL,
    stamp           VARCHAR(32)     NULL,
    op_stamp        VARCHAR(32)     NULL,
    query_string    VARCHAR(1024)   NULL,
    content_type    VARCHAR(128)    NULL,
    body_raw        MEDIUMTEXT      NULL COMMENT 'Body mentah, tidak diubah',
    body_bytes      INT UNSIGNED    NOT NULL DEFAULT 0,
    line_count      INT UNSIGNED    NOT NULL DEFAULT 0,
    parsed_count    INT UNSIGNED    NOT NULL DEFAULT 0,
    stored_count    INT UNSIGNED    NOT NULL DEFAULT 0,
    dup_count       INT UNSIGNED    NOT NULL DEFAULT 0,
    failed_count    INT UNSIGNED    NOT NULL DEFAULT 0,
    response_body   VARCHAR(255)    NULL,
    source_ip       VARCHAR(45)     NULL,
    user_agent      VARCHAR(255)    NULL,
    process_status  ENUM('received','processed','failed','skipped') NOT NULL DEFAULT 'received',
    error_message   TEXT            NULL,
    processed_at    DATETIME        NULL,
    created_at      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),

    PRIMARY KEY (id),
    KEY idx_req_device_created (device_id, created_at),
    KEY idx_req_sn_created (serial_number, created_at),
    KEY idx_req_process (process_status, created_at),
    KEY idx_req_table_created (table_name, created_at),

    CONSTRAINT fk_req_device FOREIGN KEY (device_id)
        REFERENCES device (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Arsip mentah seluruh request /iclock/*';

-- -----------------------------------------------------------------------------
-- 4. attendance_log — punch absensi
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS attendance_log (
    id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    device_id         BIGINT UNSIGNED NULL,
    serial_number     VARCHAR(64)     NOT NULL,
    pin               VARCHAR(24)     NOT NULL,
    employee_id       BIGINT UNSIGNED NULL COMMENT 'NULL bila PIN tidak dikenal',

    punch_at          DATETIME        NOT NULL COMMENT 'Waktu scan menurut DEVICE',
    punch_date        DATE            NOT NULL,
    device_tz_offset  SMALLINT        NULL,

    status_code       TINYINT         NULL COMMENT '0=in 1=out 2=break_out 3=break_in 4=ot_in 5=ot_out',
    verify_mode       TINYINT         NULL COMMENT '1=fingerprint 4=card 15=face 25=palm',
    work_code         INT             NULL,
    reserved_fields   JSON            NULL,

    record_hash       CHAR(40)        NOT NULL COMMENT 'SHA1(device|pin|punch_at|status|verify|work_code)',
    raw_line          VARCHAR(512)    NOT NULL,
    format_variant    ENUM('positional5','positionalN','keyvalue') NOT NULL,
    parse_status      ENUM('ok','partial','failed') NOT NULL DEFAULT 'ok',
    iclock_request_id BIGINT UNSIGNED NULL,
    is_processed      TINYINT(1)      NOT NULL DEFAULT 0,
    created_at        DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),

    PRIMARY KEY (id),
    UNIQUE KEY uk_attlog_hash (record_hash)
        COMMENT 'Kunci anti-duplikat untuk pengiriman ulang device',
    KEY idx_attlog_employee_time (employee_id, punch_at),
    KEY idx_attlog_pin_time (pin, punch_at),
    KEY idx_attlog_device_time (device_id, punch_at),
    KEY idx_attlog_date (punch_date),
    KEY idx_attlog_unprocessed (is_processed, punch_at),
    KEY idx_attlog_request (iclock_request_id),

    CONSTRAINT fk_attlog_device FOREIGN KEY (device_id)
        REFERENCES device (id) ON DELETE SET NULL,
    CONSTRAINT fk_attlog_employee FOREIGN KEY (employee_id)
        REFERENCES employee (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Log absensi mentah dari device';

-- -----------------------------------------------------------------------------
-- 5. device_user — mirror user yang ada di device
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS device_user (
    id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    device_id    BIGINT UNSIGNED NOT NULL,
    pin          VARCHAR(24)     NOT NULL,
    name         VARCHAR(128)    NULL,
    privilege    TINYINT         NULL COMMENT '0=user 14=admin',
    card_no      VARCHAR(32)     NULL,
    password     VARCHAR(64)     NULL COMMENT 'Sebaiknya dikosongkan',
    group_id     VARCHAR(16)     NULL,
    sync_status  ENUM('in_sync','device_only','server_only','conflict') NOT NULL DEFAULT 'in_sync',
    last_seen_at DATETIME        NULL,
    raw_line     VARCHAR(512)    NULL,
    created_at   DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at   DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP
                                 ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (id),
    UNIQUE KEY uk_device_user (device_id, pin),
    KEY idx_du_pin (pin),
    KEY idx_du_sync (sync_status),

    CONSTRAINT fk_du_device FOREIGN KEY (device_id)
        REFERENCES device (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='User yang ada di device (mirror)';

-- -----------------------------------------------------------------------------
-- 6. command_queue — antrian perintah server → device
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS command_queue (
    id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    command_id    BIGINT UNSIGNED NOT NULL COMMENT 'ID wire protocol: C:<command_id>:<cmd>',
    device_id     BIGINT UNSIGNED NOT NULL,
    command_text  VARCHAR(1024)   NOT NULL COMMENT 'Perintah tanpa prefix C:<id>:',
    command_type  VARCHAR(32)     NOT NULL,
    payload_json  JSON            NULL,
    status        ENUM('pending','sent','acked','failed','cancelled') NOT NULL DEFAULT 'pending',
    attempt_count TINYINT UNSIGNED NOT NULL DEFAULT 0,
    max_attempts  TINYINT UNSIGNED NOT NULL DEFAULT 3,
    sent_at       DATETIME        NULL,
    acked_at      DATETIME        NULL,
    return_code   INT             NULL COMMENT '0=sukses -1002=sintaks -1004=tidak didukung',
    response_raw  VARCHAR(1024)   NULL,
    error_message VARCHAR(255)    NULL,
    requested_by  BIGINT UNSIGNED NULL,
    expires_at    DATETIME        NULL,
    created_at    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP
                                  ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (id),
    UNIQUE KEY uk_cmd_command_id (command_id),
    KEY idx_cmd_device_status (device_id, status, created_at),
    KEY idx_cmd_stuck (status, sent_at),
    KEY idx_cmd_type (command_type),

    CONSTRAINT fk_cmd_device FOREIGN KEY (device_id)
        REFERENCES device (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Antrian perintah ke device, dikirim lewat getrequest';

-- -----------------------------------------------------------------------------
-- 7. device_operlog — log operasi device (bukan absensi)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS device_operlog (
    id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    device_id     BIGINT UNSIGNED NULL,
    serial_number VARCHAR(64)     NOT NULL,
    pin           VARCHAR(24)     NULL,
    log_at        DATETIME        NOT NULL,
    op_type       VARCHAR(32)     NULL,
    value1        VARCHAR(64)     NULL,
    value2        VARCHAR(64)     NULL,
    value3        VARCHAR(64)     NULL,
    record_hash   CHAR(40)        NOT NULL,
    raw_line      VARCHAR(512)    NOT NULL,
    created_at    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),

    PRIMARY KEY (id),
    UNIQUE KEY uk_operlog_hash (record_hash),
    KEY idx_operlog_device_time (device_id, log_at),

    CONSTRAINT fk_operlog_device FOREIGN KEY (device_id)
        REFERENCES device (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Log operasi device (buka pintu, alarm)';

-- =============================================================================
-- Selesai. Urutan: device → employee → iclock_request → attendance_log
--                   → device_user → command_queue → device_operlog
-- =============================================================================
