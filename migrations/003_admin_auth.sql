-- =============================================================================
-- Migrasi 003 — Autentikasi admin untuk dashboard
--
-- Dashboard admin adalah satu-satunya bagian aplikasi yang dibuka dari browser;
-- seluruh endpoint /iclock/* tetap tanpa auth karena device tidak bisa login.
-- Karena itu kredensial admin disimpan terpisah dan tidak pernah bercampur
-- dengan data device.
--
-- Jalankan SETELAH 001 dan 002:
--   mysql -u <user> -p <db> < migrations/003_admin_auth.sql
-- =============================================================================

SET NAMES utf8mb4;

-- -----------------------------------------------------------------------------
-- 13. admin_user — akun yang boleh masuk ke dashboard
--
-- Password TIDAK PERNAH disimpan apa adanya. Kolom `password_hash` menyimpan
-- hasil hash argon2id (lihat app/admin/security.py). Panjang 255 cukup untuk
-- seluruh format hash modern; jangan diciutkan.
--
-- `is_active` dipakai untuk menonaktifkan akun tanpa menghapusnya — penghapusan
-- akan memutus jejak audit siapa yang pernah mengubah data.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS admin_user (
    id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    username      VARCHAR(64)     NOT NULL,
    display_name  VARCHAR(128)    NULL,
    password_hash VARCHAR(255)    NOT NULL COMMENT 'argon2id; JANGAN pernah plaintext',
    is_active     TINYINT(1)      NOT NULL DEFAULT 1,
    is_superuser  TINYINT(1)      NOT NULL DEFAULT 0
                  COMMENT 'Superuser boleh mengelola akun admin lain',
    last_login_at DATETIME        NULL,
    created_at    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP
                                  ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (id),
    UNIQUE KEY uk_admin_username (username),
    KEY idx_admin_active (is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Akun admin dashboard';

-- -----------------------------------------------------------------------------
-- 14. admin_session — sesi login
--
-- Yang disimpan adalah HASH dari token, bukan tokennya. Alasannya sama dengan
-- password: bila isi tabel ini bocor (backup, dump, akses baca), token mentah
-- tidak langsung bisa dipakai meniru sesi orang lain. Token dikirim ke browser
-- lewat cookie HttpOnly.
--
-- Penghapusan akun CASCADE menghapus sesinya sekaligus — menonaktifkan akun
-- harus benar-benar memutus akses, bukan hanya mencegah login baru.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS admin_session (
    id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    admin_user_id  BIGINT UNSIGNED NOT NULL,
    token_hash     CHAR(64)        NOT NULL COMMENT 'SHA-256 token sesi (bukan tokennya)',
    user_agent     VARCHAR(255)    NULL,
    source_ip      VARCHAR(45)     NULL,
    expires_at     DATETIME        NOT NULL,
    revoked_at     DATETIME        NULL COMMENT 'Diisi saat logout',
    created_at     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_used_at   DATETIME        NULL,

    PRIMARY KEY (id),
    UNIQUE KEY uk_session_token (token_hash),
    KEY idx_session_user (admin_user_id),
    KEY idx_session_expiry (expires_at)
        COMMENT 'Untuk pembersihan sesi kedaluwarsa',

    CONSTRAINT fk_session_admin FOREIGN KEY (admin_user_id)
        REFERENCES admin_user (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Sesi login dashboard admin';

-- =============================================================================
-- Selesai. Total setelah migrasi 003: 15 tabel.
-- =============================================================================
