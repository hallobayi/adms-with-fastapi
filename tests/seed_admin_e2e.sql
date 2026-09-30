-- Data contoh untuk harness verifikasi dashboard admin.
--
-- Dipakai oleh `tests/verify_admin_e2e.py`. Diasumsikan skema sudah dibuat
-- oleh `migrations/001..003`. Skrip ini mengosongkan tabel lebih dulu supaya
-- bisa dijalankan berulang.
--
-- Angka-angka di sini sengaja "pas" untuk diuji:
--   1001 (Budi)  masuk 08:45 WIB vs shift 08:00 toleransi 15 -> TELAT 30 menit
--   1002 (Siti)  masuk 07:55 WIB vs shift 08:00 toleransi 15 -> TEPAT WAKTU
--   punch PIN 9999 tanpa karyawan                            -> TAK TERTAUT
--
-- Perhatikan `punch_at` (UTC) dan `punch_at_local` (WIB) sengaja BERBEDA 7 jam.
-- Harness inilah yang membuktikan perhitungan memakai jam lokal, bukan UTC.

SET FOREIGN_KEY_CHECKS = 0;
TRUNCATE attendance_log;
TRUNCATE sync_log;
TRUNCATE iclock_request;
TRUNCATE finger_template;
TRUNCATE device_user;
TRUNCATE command_queue;
TRUNCATE shift_assignment;
TRUNCATE daily_attendance;
TRUNCATE employee;
TRUNCATE shift;
TRUNCATE holiday;
TRUNCATE device;
TRUNCATE admin_session;
TRUNCATE admin_user;
SET FOREIGN_KEY_CHECKS = 1;

INSERT INTO device (serial_number, display_name, location, status, tz_name, tz_offset_minutes,
                    last_seen_at, last_handshake_at, last_attlog_at)
VALUES ('SN-TEST-1', 'Pintu Depan', 'Lantai 1', 'active', 'Asia/Jakarta', 420, NOW(), NOW(), NOW()),
       ('SN-NEW-2', 'Belum Disetujui', 'Lantai 2', 'pending', 'Asia/Jakarta', 420, NULL, NULL, NULL);

INSERT INTO employee (pin, name, employee_code, department, position, is_active)
VALUES ('1001', 'Budi Santoso', 'EMP-001', 'Produksi', 'Operator', 1),
       ('1002', 'Siti Aminah', 'EMP-002', 'Produksi', 'Operator', 1),
       ('1003', 'Andi Wijaya', 'EMP-003', 'Gudang', 'Staff', 1);

INSERT INTO shift (name, start_time, end_time, late_tolerance_min, early_leave_tol_min, is_overnight)
VALUES ('Pagi', '08:00:00', '17:00:00', 15, 10, 0),
       ('Malam', '20:00:00', '05:00:00', 10, 10, 1);

INSERT INTO shift_assignment (employee_id, shift_id, effective_from, work_days)
SELECT e.id, s.id, '2026-01-01', 'MO,TU,WE,TH,FR'
FROM employee e, shift s WHERE e.pin = '1001' AND s.name = 'Pagi';
INSERT INTO shift_assignment (employee_id, shift_id, effective_from, work_days)
SELECT e.id, s.id, '2026-01-01', 'MO,TU,WE,TH,FR'
FROM employee e, shift s WHERE e.pin = '1002' AND s.name = 'Pagi';

INSERT INTO holiday (holiday_date, name) VALUES ('2026-09-30', 'Cuti Bersama');

INSERT INTO attendance_log (device_id, serial_number, pin, employee_id, punch_at, punch_at_local,
                            tz_applied, punch_date, status_code, record_hash, raw_line, format_variant)
VALUES
 ((SELECT id FROM device WHERE serial_number = 'SN-TEST-1'), 'SN-TEST-1', '1001',
  (SELECT id FROM employee WHERE pin = '1001'),
  '2026-09-28 01:45:00', '2026-09-28 08:45:00', 'Asia/Jakarta', '2026-09-28', 0,
  'h-1001-in', 'x', 'positional5'),
 ((SELECT id FROM device WHERE serial_number = 'SN-TEST-1'), 'SN-TEST-1', '1001',
  (SELECT id FROM employee WHERE pin = '1001'),
  '2026-09-28 10:10:00', '2026-09-28 17:10:00', 'Asia/Jakarta', '2026-09-28', 1,
  'h-1001-out', 'x', 'positional5'),
 ((SELECT id FROM device WHERE serial_number = 'SN-TEST-1'), 'SN-TEST-1', '1002',
  (SELECT id FROM employee WHERE pin = '1002'),
  '2026-09-28 00:55:00', '2026-09-28 07:55:00', 'Asia/Jakarta', '2026-09-28', 0,
  'h-1002-in', 'x', 'positional5'),
 ((SELECT id FROM device WHERE serial_number = 'SN-TEST-1'), 'SN-TEST-1', '1002',
  (SELECT id FROM employee WHERE pin = '1002'),
  '2026-09-28 10:05:00', '2026-09-28 17:05:00', 'Asia/Jakarta', '2026-09-28', 1,
  'h-1002-out', 'x', 'positional5'),
 ((SELECT id FROM device WHERE serial_number = 'SN-TEST-1'), 'SN-TEST-1', '9999', NULL,
  '2026-09-28 02:00:00', '2026-09-28 09:00:00', 'Asia/Jakarta', '2026-09-28', 0,
  'h-9999', 'x', 'positional5');

-- Master + salinan device untuk slot yang sama: bahan konflik.
INSERT INTO finger_template (pin, finger_index, device_id, object_key, is_valid, sync_state)
VALUES ('1001', 0, NULL, 'obj/master-1001-0', 1, 'in_sync'),
       ('1001', 0, (SELECT id FROM device WHERE serial_number = 'SN-TEST-1'),
        'obj/device-1001-0', 1, 'in_sync');

INSERT INTO sync_log (device_id, serial_number, direction, entity_type, pin, finger_index,
                      action, outcome, conflict_detail, resolved_by)
VALUES ((SELECT id FROM device WHERE serial_number = 'SN-TEST-1'), 'SN-TEST-1', 'device_to_server',
        'finger_template', '1001', 0, 'update', 'conflict', 'server: ver7 | device: ver9', 'none'),
       ((SELECT id FROM device WHERE serial_number = 'SN-TEST-1'), 'SN-TEST-1', 'device_to_server',
        'user', '1002', NULL, 'update', 'conflict', 'nama beda', 'server_wins'),
       ((SELECT id FROM device WHERE serial_number = 'SN-TEST-1'), 'SN-TEST-1', 'server_to_device',
        'user', '1003', NULL, 'create', 'applied', NULL, 'none');

INSERT INTO iclock_request (device_id, serial_number, endpoint, http_method, table_name,
                            body_raw, body_bytes, line_count, parsed_count, stored_count,
                            dup_count, failed_count, process_status, source_ip)
VALUES ((SELECT id FROM device WHERE serial_number = 'SN-TEST-1'), 'SN-TEST-1', '/iclock/cdata',
        'POST', 'OPERLOG', 'OK: 2\n', 120, 3, 3, 2, 1, 0, 'processed', '10.0.0.5'),
       ((SELECT id FROM device WHERE serial_number = 'SN-TEST-1'), 'SN-TEST-1', '/iclock/cdata',
        'POST', 'ATTLOG', 'BROKEN\n', 80, 1, 0, 0, 0, 1, 'failed', '10.0.0.5');
