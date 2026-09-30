"""Verifikasi ujung-ke-ujung dashboard admin terhadap MySQL nyata.

Dijalankan sekali jalan bersama instance MySQL sementara (lihat skill
`mysql-schema-verify-windows`): proses latar belakang mati di antara pemanggilan
tool, jadi seluruh siklus hidup harus ada dalam satu perintah.

Yang dibuktikan di sini adalah hal-hal yang **tidak bisa** dibuktikan tanpa
database sungguhan:

- `recompute_daily` benar-benar menghitung telat dan menghormati `is_manual`.
- Konflik diselesaikan **tanpa menghapus** baris yang kalah.
- Untai `DELETE`/`RESTRICT` (shift yang masih dipakai) ditolak seperti niat.
- Perubahan PIN melaporkan punch yang tidak lagi tertaut.

Harness ini **mengasumsikan** database sudah dimigrasi dan di-seed (lihat
`tests/seed_admin_e2e.sql`, dijalankan oleh skrip pembungkus). Ia juga
**mengubah data** — ia membuat akun, menyelesaikan konflik, dan menandai
rekap manual — jadi jangan diarahkan ke database produksi.

Konfigurasi lewat environment: `VERIFY_HOST`, `VERIFY_PORT`, `VERIFY_USER`,
`VERIFY_PASSWORD`.
"""

from __future__ import annotations

import os
import sys

os.environ.update(
    MYSQL_HOST=os.environ.get("VERIFY_HOST", "127.0.0.1"),
    MYSQL_PORT=os.environ.get("VERIFY_PORT", "3399"),
    MYSQL_USER=os.environ.get("VERIFY_USER", "root"),
    # `app.config` sengaja menolak password kosong (fail-fast), jadi instance
    # sementara diberi password oleh skrip pemanggil.
    MYSQL_PASSWORD=os.environ.get("VERIFY_PASSWORD", "vsecret"),
    MYSQL_DB=os.environ.get("VERIFY_DB", "adms"),
    DEBUG="true",
)

from fastapi.testclient import TestClient  # noqa: E402

from app.application import create_app  # noqa: E402

FAILURES: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    mark = "OK  " if condition else "FAIL"
    print(f"  [{mark}] {label}" + (f"  <- {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(label)


def main() -> int:
    client = TestClient(create_app())

    # --- 1. Login ---------------------------------------------------------
    print("\n=== 1. Autentikasi ===")

    # Buat superuser langsung lewat API internal (tanpa akun awal, tak ada
    # cara login; bootstrap selalu lewat `create_admin`).
    from app.admin import auth as auth_mod
    from app.database import connection

    with connection() as conn:
        admin_id = auth_mod.create_admin(
            conn, username="root", password="SuperRahasia123", display_name="Root",
            is_superuser=True,
        )
        conn.commit()
    check("akun superuser dibuat", admin_id > 0)

    bad = client.post(
        "/api/admin/auth/login", json={"username": "root", "password": "salah"}
    )
    check("password salah ditolak 401", bad.status_code == 401, str(bad.status_code))

    req = client.post(
        "/api/admin/auth/login", json={"username": "root", "password": "SuperRahasia123"}
    )
    check("login berhasil 200", req.status_code == 200, req.text[:200])
    check("cookie HttpOnly terpasang", "adms_admin_session" in client.cookies)

    me = client.get("/api/admin/auth/me")
    check("GET /auth/me mengembalikan identitas", me.status_code == 200 and me.json()["username"] == "root")

    # --- 2. Dashboard -----------------------------------------------------
    print("\n=== 2. Ringkasan dashboard ===")
    dash = client.get("/api/admin/dashboard")
    check("GET /dashboard 200", dash.status_code == 200, dash.text[:200])
    d = dash.json()
    check("devices_total = 2", d.get("devices_total") == 2, str(d.get("devices_total")))
    check("devices_pending = 1", d.get("devices_pending") == 1, str(d.get("devices_pending")))
    check("conflicts_unresolved = 1", d.get("conflicts_unresolved") == 1, str(d))
    check("requests_failed_24h = 1", d.get("requests_failed_24h") == 1, str(d.get("requests_failed_24h")))

    # --- 3. Device --------------------------------------------------------
    print("\n=== 3. Monitoring device ===")
    devs = client.get("/api/admin/devices")
    check("GET /devices 200", devs.status_code == 200, devs.text[:200])
    body = devs.json()
    check("total device = 2", body["total"] == 2, str(body["total"]))
    first = next(x for x in body["devices"] if x["serial_number"] == "SN-TEST-1")
    check("attlog_count = 5", first["attlog_count"] == 5, str(first["attlog_count"]))
    check("unlinked_punches = 1", first["unlinked_punches"] == 1, str(first["unlinked_punches"]))

    pending = next(x for x in body["devices"] if x["serial_number"] == "SN-NEW-2")
    check("device belum pernah dilihat ada di daftar", pending["last_seen_at"] is None)

    bad_tz = client.patch(f"/api/admin/devices/{first['id']}", json={"tz_name": "Asia/Jakartaaa"})
    check("zona waktu ngawur ditolak 400", bad_tz.status_code == 400, str(bad_tz.status_code))

    good_tz = client.patch(
        f"/api/admin/devices/{first['id']}", json={"tz_name": "WIB", "location": "Lantai 1A"}
    )
    check("zona WIB diterima & dinormalkan", good_tz.status_code == 200, good_tz.text[:200])
    check("tz_name jadi Asia/Jakarta", good_tz.json()["tz_name"] == "Asia/Jakarta", good_tz.json().get("tz_name"))
    check("lokasi ikut berubah", good_tz.json()["location"] == "Lantai 1A")

    appr = client.post(f"/api/admin/devices/{pending['id']}/approve")
    check("device pending disetujui", appr.status_code == 200, appr.text[:200])
    check(
        "approve kedua kali ditolak 400",
        client.post(f"/api/admin/devices/{pending['id']}/approve").status_code == 400,
    )

    # --- 4. Arsip request -------------------------------------------------
    print("\n=== 4. Arsip request ===")
    reqs = client.get("/api/admin/requests")
    check("GET /requests 200", reqs.status_code == 200, reqs.text[:200])
    check("total request = 2", reqs.json()["total"] == 2, str(reqs.json()["total"]))
    check(
        "daftar tidak memuat body_raw",
        all(r["body_raw"] is None for r in reqs.json()["requests"]),
    )

    failed_only = client.get("/api/admin/requests", params={"process_status": "failed"})
    check("filter process_status bekerja", failed_only.json()["total"] == 1)

    # --- 5. Konflik -------------------------------------------------------
    print("\n=== 5. Konflik sinkronisasi ===")
    conf = client.get("/api/admin/conflicts")
    check("GET /conflicts 200", conf.status_code == 200, conf.text[:200])
    check("hanya konflik belum ditinjau = 1", conf.json()["total"] == 1, str(conf.json()["total"]))
    conflict = conf.json()["conflicts"][0]
    check("entity_type finger_template", conflict["entity_type"] == "finger_template")
    check("resolved_by = none", conflict["resolved_by"] == "none")

    resolved_all = client.get("/api/admin/conflicts", params={"resolved": "true"})
    check("konflik yang sudah ditinjau = 1", resolved_all.json()["total"] == 1)

    res = client.post(
        f"/api/admin/conflicts/{conflict['id']}/resolve",
        json={"resolution": "server_wins", "note": "hasil verifikasi lapangan"},
    )
    check("resolve server_wins 200", res.status_code == 200, res.text[:300])
    check("ada baris terdampak", res.json()["affected"] == 1, str(res.json()))

    twice = client.post(
        f"/api/admin/conflicts/{conflict['id']}/resolve", json={"resolution": "device_wins"}
    )
    check("resolve dua kali ditolak 400", twice.status_code == 400, str(twice.status_code))

    # Jejak audit: baris yang kalah ada, hanya dinonaktifkan.
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*), SUM(is_valid = 0), SUM(sync_state = 'conflict') "
            "FROM finger_template WHERE pin = '1001' AND finger_index = 0"
        )
        total_rows, invalid, conflicted = cur.fetchone()
    check("baris finger_template TIDAK dihapus", total_rows == 2, str(total_rows))
    check("baris yang kalah is_valid = 0", invalid == 1, str(invalid))
    check("sync_state = 'conflict'", conflicted == 1, str(conflicted))

    # --- 6. Absensi: olah ulang -------------------------------------------
    print("\n=== 6. Rekap absensi & olah ulang ===")
    rec = client.post("/api/admin/attendance/recompute", params={"work_date": "2026-09-28"})
    check("POST /attendance/recompute 200", rec.status_code == 200, rec.text[:300])
    stats = rec.json()
    check("2 karyawan punya punch", stats["employees"] == 2, str(stats))
    check("2 baris dibuat", stats["created"] == 2, str(stats))
    check("belum ada yang dilewati", stats["skipped_manual"] == 0, str(stats))

    att = client.get("/api/admin/attendance", params={"work_date": "2026-09-28"})
    check("GET /attendance 200", att.status_code == 200, att.text[:300])
    rows = {r["pin"]: r for r in att.json()["attendance"]}
    check("rekap memuat 2 karyawan", len(rows) == 2, str(list(rows)))

    budi = rows.get("1001")
    check("1001 berstatus late", budi and budi["status"] == "late", str(budi and budi["status"]))
    check("1001 late_minutes = 30", budi and budi["late_minutes"] == 30, str(budi and budi["late_minutes"]))
    check("1001 early_leave = 0", budi and budi["early_leave_minutes"] == 0, str(budi and budi["early_leave_minutes"]))
    check("1001 punch_count = 2", budi and budi["punch_count"] == 2)
    check("1001 worked_minutes = 505", budi and budi["worked_minutes"] == 505, str(budi and budi["worked_minutes"]))

    siti = rows.get("1002")
    check("1002 berstatus present", siti and siti["status"] == "present", str(siti and siti["status"]))
    check("1002 late_minutes = 0", siti and siti["late_minutes"] == 0)

    check("ringkasan late = 1", att.json()["summary"]["late"] == 1, str(att.json()["summary"]))

    # --- 7. Absensi: koreksi manual bertahan ------------------------------
    print("\n=== 7. Koreksi manual tidak ditimpa olah ulang ===")
    corr = client.patch(
        f"/api/admin/attendance/{budi['id']}",
        json={"status": "present", "late_minutes": 0, "note": "macet, sudah dikonfirmasi atasan"},
    )
    check("PATCH koreksi 200", corr.status_code == 200, corr.text[:300])

    again = client.post("/api/admin/attendance/recompute", params={"work_date": "2026-09-28"})
    check("olah ulang kedua: 1 baris dilewati", again.json()["skipped_manual"] == 1, str(again.json()))
    # Yang diolah ulang hanya baris non-manual (1002), jadi `updated` = 1.
    check("olah ulang kedua: hanya 1 baris (non-manual) diperbarui",
          again.json()["updated"] == 1, str(again.json()))

    after = client.get("/api/admin/attendance", params={"work_date": "2026-09-28"})
    budi_after = next(r for r in after.json()["attendance"] if r["pin"] == "1001")
    check("koreksi manual BERTAHAN (late=0)", budi_after["late_minutes"] == 0, str(budi_after))
    check("status tetap 'present'", budi_after["status"] == "present", budi_after["status"])
    check("is_manual = true", budi_after["is_manual"] is True)
    check("catatan tersimpan", budi_after["note"] == "macet, sudah dikonfirmasi atasan")

    forced = client.post(
        "/api/admin/attendance/recompute",
        params={"work_date": "2026-09-28", "overwrite_manual": "true"},
    )
    # Dua karyawan diproses ulang, dan kali ini baris manual ikut ditimpa.
    check("overwrite_manual=true menimpa kedua baris",
          forced.json()["updated"] == 2 and forced.json()["skipped_manual"] == 0,
          str(forced.json()))

    # Kembalikan koreksi manual untuk sisa uji.
    client.patch(f"/api/admin/attendance/{budi['id']}", json={"late_minutes": 0})

    # --- 8. Olah ulang hari libur -----------------------------------------
    print("\n=== 8. Hari libur ditandai 'holiday' ===")
    client.post("/api/admin/attendance/recompute", params={"work_date": "2026-09-30"})
    # Belum ada punch pada 30 Sep; buat satu lalu olah ulang.
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO attendance_log
                (device_id, serial_number, pin, employee_id, punch_at, punch_at_local,
                 tz_applied, punch_date, status_code, record_hash, raw_line, format_variant)
            SELECT d.id, 'SN-TEST-1', '1003', e.id, '2026-09-30 01:00:00',
                   '2026-09-30 08:00:00', 'Asia/Jakarta', '2026-09-30', 0,
                   'h-libur-1003', 'libur', 'positional5'
            FROM device d, employee e
            WHERE d.serial_number = 'SN-TEST-1' AND e.pin = '1003'
            """
        )
        conn.commit()
    hol = client.post("/api/admin/attendance/recompute", params={"work_date": "2026-09-30"})
    check("olah ulang 30 Sep 200", hol.status_code == 200, hol.text[:200])
    hol_att = client.get("/api/admin/attendance", params={"work_date": "2026-09-30"})
    check(
        "punch di hari libur berstatus 'holiday'",
        hol_att.json()["attendance"][0]["status"] == "holiday",
        hol_att.json()["attendance"][0]["status"],
    )

    # --- 9. Data master: karyawan -----------------------------------------
    print("\n=== 9. CRUD karyawan ===")
    created = client.post(
        "/api/admin/employees",
        json={"pin": "2001", "name": "Dewi Lestari", "department": "HR", "position": "Staff"},
    )
    check("POST /employees 201", created.status_code == 201, created.text[:300])
    new_emp = created.json()
    check("PIN tersimpan", new_emp["pin"] == "2001")

    dup = client.post("/api/admin/employees", json={"pin": "2001", "name": "Kembar"})
    check("PIN ganda ditolak 409", dup.status_code == 409, str(dup.status_code))

    deps = client.get("/api/admin/employees/departments")
    check("departemen unik memuat HR", "HR" in deps.json()["departments"], str(deps.json()))

    # Ubah PIN 1002 -> 1002B: punch lamanya harus dilaporkan terputus.
    siti_id = next(e["id"] for e in client.get("/api/admin/employees").json()["employees"] if e["pin"] == "1002")
    pin_change = client.patch(f"/api/admin/employees/{siti_id}", json={"pin": "1002B"})
    check("ganti PIN 200", pin_change.status_code == 200, pin_change.text[:300])
    check(
        "punch lama dilaporkan terputus (2)",
        pin_change.json()["unlinked_punches"] == 2,
        str(pin_change.json()),
    )
    check("PIN baru berlaku", pin_change.json()["employee"]["pin"] == "1002B")

    with connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM attendance_log WHERE pin = '1002' AND employee_id IS NULL")
        detached = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM attendance_log WHERE pin = '1002' AND employee_id IS NOT NULL")
        still_linked = cur.fetchone()[0]
    check("punch benar-benar kehilangan tautan", detached == 2, str(detached))
    check("punch TIDAK dihapus, hanya dilepas", still_linked == 0 and detached == 2)

    # Kembalikan PIN supaya tidak mengganggu pemeriksaan lain.
    client.patch(f"/api/admin/employees/{siti_id}", json={"pin": "1002"})

    # --- 10. Data master: shift & RESTRICT --------------------------------
    print("\n=== 10. CRUD shift (termasuk RESTRICT) ===")
    shift_created = client.post(
        "/api/admin/shifts",
        json={"name": "Sore", "start_time": "14:00", "end_time": "22:00", "late_tolerance_min": 5},
    )
    check("POST /shifts 201", shift_created.status_code == 201, shift_created.text[:300])
    sore = shift_created.json()
    check("start_time dinormalkan", sore["start_time"] == "14:00:00", sore["start_time"])

    # Shift 'Pagi' masih dipakai 2 penugasan -> hapus harus 409.
    pagi_id = next(s["id"] for s in client.get("/api/admin/shifts").json()["shifts"] if s["name"] == "Pagi")
    blocked = client.delete(f"/api/admin/shifts/{pagi_id}")
    check("hapus shift terpakai ditolak 409", blocked.status_code == 409, str(blocked.status_code))
    check("pesan menyebut jumlah penugasan", "penugasan" in blocked.json()["detail"].lower(), blocked.json()["detail"])

    free_del = client.delete(f"/api/admin/shifts/{sore['id']}")
    check("hapus shift tak terpakai 200", free_del.status_code == 200, free_del.text[:200])

    # --- 11. Penugasan shift ----------------------------------------------
    print("\n=== 11. Penugasan shift ===")
    dewi_id = new_emp["id"]
    malam_id = next(s["id"] for s in client.get("/api/admin/shifts").json()["shifts"] if s["name"] == "Malam")
    asg = client.post(
        "/api/admin/shift-assignments",
        json={"employee_id": dewi_id, "shift_id": malam_id, "effective_from": "2026-10-01",
              "work_days": ["MO", "TU", "WE"]},
    )
    check("POST /shift-assignments 201", asg.status_code == 201, asg.text[:300])

    dup_asg = client.post(
        "/api/admin/shift-assignments",
        json={"employee_id": dewi_id, "shift_id": malam_id, "effective_from": "2026-10-01"},
    )
    check("penugasan ganda ditolak 409", dup_asg.status_code == 409, str(dup_asg.status_code))

    lst = client.get("/api/admin/shift-assignments", params={"employee_id": dewi_id})
    check("work_days kembali sebagai daftar", lst.json()["assignments"][0]["work_days"] == ["MO", "TU", "WE"], str(lst.json()["assignments"][0]["work_days"]))

    # --- 12. Hari libur ---------------------------------------------------
    print("\n=== 12. CRUD hari libur ===")
    hol_new = client.post("/api/admin/holidays", json={"holiday_date": "2026-12-25", "name": "Natal"})
    check("POST /holidays 201", hol_new.status_code == 201, hol_new.text[:300])
    check("tanggal kembali sebagai string", hol_new.json()["holiday_date"] == "2026-12-25")
    check(
        "hari libur ganda ditolak 409",
        client.post("/api/admin/holidays", json={"holiday_date": "2026-12-25", "name": "Lagi"}).status_code == 409,
    )
    check("hapus hari libur 200", client.delete(f"/api/admin/holidays/{hol_new.json()['id']}").status_code == 200)

    # --- 13. Akun admin (superuser) ---------------------------------------
    print("\n=== 13. Kelola akun admin ===")
    acc = client.post(
        "/api/admin/accounts",
        json={"username": "operator1", "password": "PasswordKuat99", "display_name": "Operator"},
    )
    check("POST /accounts 201", acc.status_code == 201, acc.text[:300])
    check("username ganda ditolak 409", client.post(
        "/api/admin/accounts", json={"username": "operator1", "password": "PasswordKuat99"}
    ).status_code == 409)

    self_demote = client.patch(f"/api/admin/accounts/{admin_id}", json={"is_superuser": False})
    check("superuser tak bisa menurunkan dirinya sendiri", self_demote.status_code == 400, self_demote.text[:200])
    self_off = client.patch(f"/api/admin/accounts/{admin_id}", json={"is_active": False})
    check("superuser tak bisa menonaktifkan dirinya sendiri", self_off.status_code == 400, self_off.text[:200])

    ops = next(a for a in client.get("/api/admin/accounts").json()["accounts"] if a["username"] == "operator1")
    deact = client.patch(f"/api/admin/accounts/{ops['id']}", json={"is_active": False})
    check("menonaktifkan akun lain 200", deact.status_code == 200, deact.text[:200])

    # Akun nonaktif tidak bisa login.
    blocked_login = TestClient(create_app()).post(
        "/api/admin/auth/login", json={"username": "operator1", "password": "PasswordKuat98"}
    )
    check("akun nonaktif tidak bisa login", blocked_login.status_code == 401, str(blocked_login.status_code))

    # --- 14. Ganti password sendiri mencabut sesi --------------------------
    print("\n=== 14. Ganti password & pencabutan sesi ===")
    chg = client.post(
        "/api/admin/auth/password",
        json={"current_password": "SuperRahasia123", "new_password": "GantiBaru456"},
    )
    check("ganti password 200", chg.status_code == 200, chg.text[:200])
    check("sesi sekarang dicabut (401)", client.get("/api/admin/auth/me").status_code == 401)

    relogin = TestClient(create_app()).post(
        "/api/admin/auth/login", json={"username": "root", "password": "GantiBaru456"}
    )
    check("login dengan password baru 200", relogin.status_code == 200, relogin.text[:200])
    old_pw = TestClient(create_app()).post(
        "/api/admin/auth/login", json={"username": "root", "password": "SuperRahasia123"}
    )
    check("password lama tidak berlaku", old_pw.status_code == 401)

    # --- 15. Logout -------------------------------------------------------
    print("\n=== 15. Logout ===")
    fresh = TestClient(create_app())
    fresh.post("/api/admin/auth/login", json={"username": "root", "password": "GantiBaru456"})
    check("login lagi 200", fresh.get("/api/admin/auth/me").status_code == 200)
    check("logout 200", fresh.post("/api/admin/auth/logout").status_code == 200)
    check("setelah logout 401", fresh.get("/api/admin/auth/me").status_code == 401)
    check("logout ulang tetap 200", fresh.post("/api/admin/auth/logout").status_code == 200)

    # --- Ringkasan --------------------------------------------------------
    print("\n" + "=" * 60)
    if FAILURES:
        print(f"GAGAL: {len(FAILURES)} pemeriksaan")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("SEMUA PEMERIKSAAN LULUS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
