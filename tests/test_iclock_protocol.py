"""Uji modul protokol wire iClock/ADMS.

Modul ini murni (tanpa DB, tanpa HTTP), jadi seluruhnya bisa diuji cepat.
Yang diuji di sini adalah hal-hal yang **tidak memunculkan error** kalau salah
— device hanya diam, dan itu jenis kegagalan yang paling sulit dilacak.
"""

from __future__ import annotations

from datetime import datetime

from app.iclock import protocol


def test_frame_menulis_prefix_c_id() -> None:
    assert protocol.frame(42, "CHECK") == "C:42:CHECK"


def test_handshake_terminasi_crlf_bukan_lf() -> None:
    """CRLF wajib. LF saja pernah membuat device diam tanpa keluhan."""
    response = protocol.handshake_response("SN123", op_stamp=1_700_000_000)

    assert response.count("\r\n") == 12
    # Tidak boleh ada LF yang tidak didahului CR.
    assert "\n" not in response.replace("\r\n", "")
    assert response.startswith("GET OPTION FROM: SN123\r\n")


def test_handshake_tidak_mengirim_timezone() -> None:
    """`TimeZone` sengaja dihilangkan.

    Implementasi referensi dan deployment X100C yang jalan sama-sama tidak
    mengirimnya; zona diterapkan saat menafsirkan timestamp, bukan di sini.
    """
    response = protocol.handshake_response("SN123", op_stamp=1)

    assert "TimeZone" not in response


def test_handshake_opstamp_unix_timestamp_bukan_tanggal() -> None:
    """`OpStamp` adalah unix timestamp.

    Nilai terformat (`Y-m-d H:i:s`) pernah dipakai dan membuat device menolak
    seluruh blok opsi — kegagalan senyap yang mahal.
    """
    response = protocol.handshake_response("SN123", op_stamp=1_790_715_265)

    assert "OpStamp=1790715265" in response
    assert "-" not in response.split("OpStamp=")[1].split("\r\n")[0]


def test_handshake_transflag_default_menyalakan_enroll_fp() -> None:
    """Bit 6/7 harus menyala.

    Tanpa keduanya, device tidak pernah mengunggah template sidik jari saat
    didaftarkan — persis yang terjadi pada nilai lama `1111000000`.
    """
    flag = protocol.DEFAULT_TRANS_FLAG

    assert len(flag) == 10
    assert flag[5] == "1", "posisi ke-6 (EnrollFP) harus 1"
    assert flag[6] == "1", "posisi ke-7 (ChgFP) harus 1"


def test_handshake_transflag_dapat_dikonfigurasi() -> None:
    response = protocol.handshake_response("SN1", op_stamp=1, trans_flag="1111000000")

    assert "TransFlag=1111000000" in response


def test_update_userinfo_field_kosong_bukan_placeholder() -> None:
    """`Passwd=`/`Card=` kosong adalah bentuk yang diharapkan device."""
    payload = protocol.update_userinfo("0012", "Budi Santoso")

    assert "\tPasswd=\t" in payload
    assert "\tCard=\t" in payload
    assert "TZ=0000000100000000" in payload
    assert payload.startswith("DATA UPDATE USERINFO PIN=0012")


def test_update_finger_tmp_size_nol_jatuh_ke_panjang_payload() -> None:
    """`Size=0` tidak bermakna: template tidak mungkin nol byte."""
    payload = protocol.update_finger_tmp("1", 0, 0, 1, "AAAA")

    assert "\tSize=4\t" in payload


def test_update_finger_tmp_valid_nol_dipertahankan() -> None:
    """`Valid=0` BERMAKNA dan harus diteruskan apa adanya.

    Ini flag milik device: mengubahnya menjadi 1 berarti server menyatakan
    valid template yang device bilang tidak valid.
    """
    payload = protocol.update_finger_tmp("1", 0, 1404, 0, "AAAA")

    assert "\tValid=0\t" in payload


def test_update_finger_tmp_valid_none_menjadi_satu() -> None:
    """`None` (tidak diketahui) baru diisi default 1."""
    payload = protocol.update_finger_tmp("1", 0, 1404, None, "AAAA")

    assert "\tValid=1\t" in payload


def test_delete_finger_tmp_memakai_tab_sungguhan() -> None:
    """Pemisah harus TAB asli, bukan `\\t` literal.

    Di PHP versi aslinya, kesalahan ini terbaca device sebagai satu nama field
    yang rusak.
    """
    payload = protocol.delete_finger_tmp("0012", 3)

    assert payload == "DATA DELETE FINGERTMP PIN=0012\tFID=3"
    assert "\\t" not in payload


def test_encode_datetime_rumus_protokol() -> None:
    """Verifikasi rumus packed DateTime milik device.

    Device menghitung (tanggal-1) dalam bulan, bulan dalam tahun (31 hari),
    dan tahun sejak 2000.
    """
    moment = datetime(2000, 1, 1, 0, 0, 0)
    assert protocol.encode_datetime(moment) == 0

    # 2000-01-02 00:00:00 -> satu hari penuh dalam detik
    assert protocol.encode_datetime(datetime(2000, 1, 2, 0, 0, 0)) == 86_400

    # 2000-02-01 00:00:00 -> 31 hari
    assert protocol.encode_datetime(datetime(2000, 2, 1, 0, 0, 0)) == 31 * 86_400

    # 2001-01-01 00:00:00 -> 12*31 hari
    assert protocol.encode_datetime(datetime(2001, 1, 1, 0, 0, 0)) == 12 * 31 * 86_400


def test_encode_datetime_menghitung_jam_menit_detik() -> None:
    moment = datetime(2000, 1, 1, 1, 2, 3)
    assert protocol.encode_datetime(moment) == 3600 + 120 + 3


def test_encode_datetime_bolak_balik_dengan_decode() -> None:
    """Encode lalu decode harus kembali ke nilai semula."""
    original = datetime(2026, 9, 29, 8, 15, 3)
    encoded = protocol.encode_datetime(original)

    decoded = protocol.decode_datetime(encoded)
    assert decoded == original


def test_table_kind_mengelompokkan_dengan_benar() -> None:
    assert protocol.table_kind("ATTLOG") == "attendance"
    assert protocol.table_kind("attlog") == "attendance"
    assert protocol.table_kind("OPERLOG") == "biometric"
    assert protocol.table_kind("OPLOG") == "biometric"
    assert protocol.table_kind("USERINFO") == "userinfo"
    # table yang tidak dikenal dianggap absensi: lebih aman menyimpannya
    # sebagai punch daripada membuangnya.
    assert protocol.table_kind(None) == "attendance"
    assert protocol.table_kind("SESUATU") == "attendance"


def test_restart_device_kode_firmware() -> None:
    assert protocol.restart_device() == "CONTROL DEVICE 03000000"


def test_check_tanpa_parameter() -> None:
    assert protocol.check() == "CHECK"
