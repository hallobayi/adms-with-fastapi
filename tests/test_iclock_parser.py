"""Uji parser muatan device.

Yang diuji di sini adalah kasus-kasus yang **tidak memunculkan error tapi
menghasilkan data salah** — persis jenis kegagalan yang paling lama tidak
terdeteksi di produksi.
"""

from __future__ import annotations

from datetime import datetime

from app.iclock import parser


# --- Timestamp ------------------------------------------------------------


def test_parse_datetime_format_standar() -> None:
    assert parser.parse_datetime("2026-09-29 08:15:03") == datetime(2026, 9, 29, 8, 15, 3)


def test_parse_datetime_pemisah_t() -> None:
    assert parser.parse_datetime("2026-09-29T08:15:03") == datetime(2026, 9, 29, 8, 15, 3)


def test_parse_datetime_format_padat() -> None:
    """Firmware tertentu mengirim `20260929081503`, bukan bentuk berstrip."""
    assert parser.parse_datetime("20260929081503") == datetime(2026, 9, 29, 8, 15, 3)


def test_parse_datetime_tanggal_tidak_valid_mengembalikan_none() -> None:
    """31 Februari harus ditolak, bukan dilempar sebagai exception."""
    assert parser.parse_datetime("2026-02-31 00:00:00") is None


def test_parse_datetime_kosong_mengembalikan_none() -> None:
    assert parser.parse_datetime("") is None
    assert parser.parse_datetime("   ") is None


# --- ATTLOG posisional ----------------------------------------------------


def test_attlog_positional5() -> None:
    line = "0012\t2026-09-29 08:15:03\t0\t1\t0"
    record = parser.parse_attendance_line(line)

    assert record is not None
    assert record.pin == "0012"
    assert record.punch_at_local == datetime(2026, 9, 29, 8, 15, 3)
    assert record.status_code == 0
    assert record.verify_mode == 1
    assert record.work_code == 0
    assert record.format_variant == "positional5"
    assert record.status_label == "check_in"
    assert record.verify_label == "fingerprint"


def test_attlog_positional_n_kolom_ekstra_masuk_reserved() -> None:
    line = "0012\t2026-09-29 17:30:00\t1\t1\t0\t999\tEXTRA"
    record = parser.parse_attendance_line(line)

    assert record is not None
    assert record.format_variant == "positionalN"
    assert record.reserved == ["999", "EXTRA"]


def test_attlog_keyvalue() -> None:
    line = "PIN=0012\tDateTime=2026-09-29 08:15:03\tStatus=0\tVerified=1"
    record = parser.parse_attendance_line(line)

    assert record is not None
    assert record.pin == "0012"
    assert record.status_code == 0
    assert record.verify_mode == 1
    assert record.format_variant == "keyvalue"


def test_attlog_kolom_kurang_dilewati_bukan_menggagalkan() -> None:
    """Satu baris rusak tidak boleh membuang seluruh batch."""
    payload = "\n".join(
        [
            "0012\t2026-09-29 08:15:03\t0\t1\t0",
            "rusak",
            "0013\t2026-09-29 09:00:00\t0\t1\t0",
        ]
    )
    records = parser.parse_attendance(payload)

    assert len(records) == 2
    assert {r.pin for r in records} == {"0012", "0013"}


def test_attlog_timestamp_rusak_dilewati() -> None:
    payload = "\n".join(
        [
            "0012\tBUKAN-TANGGAL\t0\t1\t0",
            "0013\t2026-09-29 09:00:00\t0\t1\t0",
        ]
    )
    records = parser.parse_attendance(payload)

    assert len(records) == 1
    assert records[0].pin == "0013"


def test_attlog_crlf_dan_lf_sama_saja() -> None:
    crlf = "0012\t2026-09-29 08:15:03\t0\t1\t0\r\n0013\t2026-09-29 09:00:00\t0\t1\t0"
    lf = crlf.replace("\r\n", "\n")

    assert len(parser.parse_attendance(crlf)) == 2
    assert len(parser.parse_attendance(lf)) == 2


def test_attlog_tanda_koma_tidak_memecah_field() -> None:
    """Pemisah adalah TAB; koma tidak boleh memecah apa pun.

    Implementasi lama memecah pada koma juga, dan itu merusak field yang
    memang berisi koma.
    """
    line = "0012\t2026-09-29 08:15:03\t0\t1\t0"
    record = parser.parse_attendance_line(line)

    assert record is not None
    assert record.punch_at_local == datetime(2026, 9, 29, 8, 15, 3)


# --- Muatan biometrik -----------------------------------------------------


def test_fingerprint_legacy_fp() -> None:
    # Tag dan field pertama dipisah TAB: `FP\tPIN=...`. Menuliskan `FP PIN=...`
    # (dipisah spasi) adalah kesalahan yang mudah terjadi, dan parser memang
    # harus menolaknya — lihat test_fingerprint_tag_dipisah_spasi_ditolak.
    line = "FP\tPIN=0012\tFID=0\tSize=1404\tValid=1\tTMP=AAAA"
    record = parser.parse_fingerprint_line(line)

    assert record is not None
    assert record.pin == "0012"
    assert record.finger_index == 0
    assert record.size == 1404
    assert record.valid == 1
    assert record.template == "AAAA"
    assert record.tag == "FP"


def test_fingerprint_biodata_type1_dikenali() -> None:
    """PUSH SDK 2.x memakai tag `BIODATA` dengan `Type=1` untuk sidik jari."""
    line = (
        "BIODATA\tPin=0012\tNo=1\tIndex=1\tValid=1\tDuress=0\tType=1"
        "\tMajorVer=39\tTmp=BBBB"
    )
    record = parser.parse_fingerprint_line(line)

    assert record is not None
    assert record.pin == "0012"
    assert record.finger_index == 1
    assert record.template == "BBBB"


def test_fingerprint_biodata_tipe_bukan_jari_diabaikan() -> None:
    """Type selain 1 (wajah/palm/vena) bukan urusan kita."""
    line = "BIODATA\tPin=0012\tNo=50\tType=3\tTmp=CCCC"

    assert parser.parse_fingerprint_line(line) is None


def test_fingerprint_tag_dipisah_spasi_ditolak() -> None:
    """`FP PIN=...` (spasi) bukan wire format yang sah — pemisahnya TAB.

    Parser sengaja tidak "memaklumi" bentuk ini: melonggarkan deteksi tag
    berarti baris ATTLOG yang kebetulan berawalan 'FP' ikut dianggap template.
    """
    assert parser.parse_fingerprint_line("FP PIN=0012\tFID=0\tTMP=AAAA") is None


def test_fingerprint_tanpa_template_diabaikan() -> None:
    assert parser.parse_fingerprint_line("FP\tPIN=0012\tFID=0\tSize=100") is None


def test_fingerprint_base64_berpadding_utuh() -> None:
    """`TMP=` adalah base64; padding `=` tidak boleh hilang.

    Pemisahan pada `=` pertama menjaga nilai ini tetap utuh.
    """
    line = "FP\tPIN=1\tFID=0\tTMP=SGVsbG8gV29ybGQ="
    record = parser.parse_fingerprint_line(line)

    assert record is not None
    assert record.template == "SGVsbG8gV29ybGQ="
    assert parser.decode_template(record.template) == b"Hello World"


def test_decode_template_base64_tidak_valid_tetap_disimpan() -> None:
    """Lebih baik menyimpan mentah daripada membuang data."""
    result = parser.decode_template("!bukan-base64!")

    assert result == b"!bukan-base64!"


def test_decode_template_menghitung_ukuran_nyata() -> None:
    result = parser.decode_template("SGVsbG8gV29ybGQ=")

    assert len(result) == 11


# --- Data user ------------------------------------------------------------


def test_parse_user_mempertahankan_nama_berspasi() -> None:
    """Nama user sah mengandung spasi — pemisahan harus TAB, bukan spasi."""
    line = (
        "USER\tPIN=0012\tName=Budi Santoso Wijaya\tPri=0\tPasswd=\tCard=\tGrp=1"
        "\tTZ=0000000100000000"
    )
    users = parser.parse_users(line)

    assert len(users) == 1
    assert users[0].pin == "0012"
    assert users[0].name == "Budi Santoso Wijaya"
    assert users[0].group_id == "1"


def test_parse_user_lewatkan_baris_bukan_user() -> None:
    payload = "\n".join(
        [
            "USER\tPIN=0012\tName=Budi",
            "FP\tPIN=0012\tFID=0\tTMP=AAAA",
        ]
    )
    users = parser.parse_users(payload)

    assert len(users) == 1


# --- Deteksi & konfirmasi -------------------------------------------------


def test_looks_like_biometric_payload() -> None:
    assert parser.looks_like_biometric_payload("FP\tPIN=1\tFID=0\tTMP=AA")
    assert parser.looks_like_biometric_payload("BIODATA\tPin=1\tType=1\tTmp=AA")
    assert parser.looks_like_biometric_payload("USER\tPIN=1\tName=Budi")
    assert not parser.looks_like_biometric_payload("0012\t2026-09-29 08:15:03\t0\t1\t0")


def test_parse_command_acks_gaya_ampersand() -> None:
    acks = parser.parse_command_acks("ID=123&Return=0&CMD=DATA")

    assert acks == [(123, 0)]


def test_parse_command_acks_gaya_tab() -> None:
    acks = parser.parse_command_acks("ID=123\tReturn=-1004\tCMD=DATA")

    assert acks == [(123, -1004)]


def test_parse_command_acks_banyak_baris() -> None:
    body = "ID=1&Return=0&CMD=DATA\r\nID=2&Return=-1002&CMD=DATA"
    acks = parser.parse_command_acks(body)

    assert acks == [(1, 0), (2, -1002)]


def test_parse_command_acks_tanpa_id_kosong() -> None:
    assert parser.parse_command_acks("Return=0&CMD=DATA") == []
    assert parser.parse_command_acks("") == []


def test_parse_command_acks_return_hilang_dianggap_gagal() -> None:
    """Tanpa `Return=`, jangan diam-diam menganggap sukses."""
    acks = parser.parse_command_acks("ID=5&CMD=DATA")

    assert acks == [(5, -1)]


# --- Muatan gabungan ------------------------------------------------------


def test_payload_campuran_user_dan_fingerprint() -> None:
    """Satu muatan OPERLOG bisa memuat user dan template sekaligus."""
    payload = "\r\n".join(
        [
            "USER\tPIN=0012\tName=Budi Santoso\tPri=0",
            "FP\tPIN=0012\tFID=0\tSize=4\tValid=1\tTMP=AAAA",
            "FP\tPIN=0012\tFID=1\tSize=4\tValid=1\tTMP=BBBB",
        ]
    )

    assert len(parser.parse_users(payload)) == 1
    assert len(parser.parse_fingerprints(payload)) == 2
