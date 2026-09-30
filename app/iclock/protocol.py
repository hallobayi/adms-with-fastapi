"""Kosakata protokol wire iClock/ADMS — satu-satunya tempat yang mengetahuinya.

Setiap perintah yang dikirim ke device selalu dibingkai sama::

    C:<cmd_id>:<payload>

Modul ini sengaja murni (tanpa dependensi apa pun). Alasannya: format protokol
adalah hal yang paling sering salah ditulis ulang di tempat berbeda-beda, dan
kesalahannya tidak memunculkan error — device hanya diam. Dengan menyatukannya
di sini, format bisa diuji langsung tanpa database maupun HTTP.

Sumber format: `iclockController.php` dan `AdmsProtocol.php` pada
`hallobayi/webroster-adms-server` (implementasi Laravel yang terbukti jalan di
X100C), plus catatan protokol ZKTeco.
"""

from __future__ import annotations

from datetime import datetime

# --- Jenis perintah -------------------------------------------------------
# Dipakai sebagai nilai `command_queue.command_type` supaya konfirmasi device
# bisa dikaitkan kembali ke operasi yang menghasilkannya.

TYPE_USERINFO_UPSERT = "userinfo_upsert"
TYPE_USERINFO_DELETE = "userinfo_delete"
TYPE_FINGERTMP_DELETE = "fingertmp_delete"
TYPE_DEVICE_RESTART = "device_restart"
TYPE_SET_DATETIME = "set_datetime"
TYPE_PULL_CHECK = "pull_check"
TYPE_PULL_FINGERTMP = "pull_fingertmp"
TYPE_PULL_USERINFO = "pull_userinfo"
TYPE_PUSH_FINGERTMP = "push_fingertmp"

# Tanda `Return=` pada konfirmasi device yang berarti sukses.
RETURN_OK = 0


def frame(cmd_id: int, payload: str) -> str:
    """Bungkus payload menjadi baris perintah lengkap.

    Satu-satunya tempat prefix ``C:{cmd_id}:`` ditulis.
    """
    return f"C:{cmd_id}:{payload}"


# --- Data user ------------------------------------------------------------


def update_userinfo(pin: str | int | None, name: str | int | None) -> str:
    """Kirim data user lengkap (upsert).

    Device melakukan upsert berdasarkan PIN, jadi satu perintah ini menangani
    pembuatan **dan** pembaruan — tidak ada instruksi "create user" terpisah
    di ADMS.

    Field kosong (`Passwd=`, `Card=`) dan nilai default (`Grp`, `TZ`, `Pri`,
    `Category`) adalah bentuk yang diharapkan device, bukan placeholder.
    """
    return (
        f"DATA UPDATE USERINFO PIN={pin}\tName={name}\tPasswd=\tCard="
        "\tGrp=1\tTZ=0000000100000000\tPri=0\tCategory=0"
    )


def delete_userinfo(pin: str | int | None) -> str:
    """Hapus user beserta seluruh template miliknya."""
    return f"DATA DELETE USERINFO PIN={pin}"


def query_userinfo(pin: str | int | None = "") -> str:
    """Minta data user. PIN kosong berarti "semua user yang dipegang device"."""
    return f"DATA QUERY USERINFO PIN={pin}"


# --- Biometrik ------------------------------------------------------------


def check() -> str:
    """Minta device mengunggah ulang seluruh isinya (best-effort)."""
    return "CHECK"


def query_finger_tmp(pin: str | int | None, fid: int) -> str:
    """Minta satu jari dari satu karyawan. Satu perintah per jari."""
    return f"DATA QUERY FINGERTMP PIN={pin}\tFingerID={fid}"


def update_finger_tmp(
    pin: str | int | None,
    fid: int,
    size: int | None,
    valid: int | None,
    template: str,
) -> str:
    """Kirim template sidik jari ke device.

    Dua nilai default di sini sengaja **tidak** sama, karena dua angka nol itu
    artinya berbeda:

    - ``Size=0`` tidak bermakna (template tidak mungkin nol byte), jadi ukuran
      kosong/nol jatuh ke panjang payload yang sebenarnya — itu setidaknya
      benar.
    - ``Valid=0`` **bermakna**. Itu flag milik device, bukan milik kita: device
      melaporkannya saat mengunggah ("FP PIN=.. Valid=0"), dan ZKTeco SDK
      meneruskannya apa adanya. Mengubah 0 menjadi 1 berarti server menyatakan
      valid sebuah template yang device bilang tidak valid. Karena itu di sini
      dipakai ``is None`` (mengisi yang kosong), **bukan** ``or`` (yang ikut
      menimpa nol).
    """
    resolved_size = size if size else len(template)
    resolved_valid = 1 if valid is None else valid
    return (
        f"DATA UPDATE FINGERTMP PIN={pin}\tFID={fid}\tSize={resolved_size}"
        f"\tValid={resolved_valid}\tTMP={template}"
    )


def delete_finger_tmp(pin: str | int | None, fid: int) -> str:
    """Hapus satu jari saja; data user tetap ada.

    Tidak ada bentuk "semua jari" di protokol ini — ZKTeco SDK hanya
    mendefinisikan bentuk PIN+FID, jadi menghapus semua jari berarti satu
    perintah per indeks.
    """
    return f"DATA DELETE FINGERTMP PIN={pin}\tFID={fid}"


# --- Kontrol device -------------------------------------------------------


def restart_device() -> str:
    """Reboot device. `03000000` adalah kode kontrol yang dikenali firmware."""
    return "CONTROL DEVICE 03000000"


def set_datetime(encoded: int) -> str:
    """Set jam device. `encoded` adalah format packed milik device."""
    return f"SET OPTIONS DateTime={encoded}"


def encode_datetime(moment: datetime) -> int:
    """Kemas waktu ke format DateTime milik device.

    Bukan unix timestamp dan bukan string terformat: device menghitung
    (tanggal-1) dalam bulan, bulan dalam tahun, dan tahun sejak 2000.

    Pemanggil harus sudah memberikan waktu yang **sudah** dinyatakan dalam zona
    device — fungsi ini sengaja tidak melakukan konversi zona sendiri, karena
    hanya pemanggil yang tahu zona mana yang berlaku.
    """
    return (
        ((moment.year - 2000) * 12 * 31 + ((moment.month - 1) * 31) + moment.day - 1)
        * (24 * 60 * 60)
        + (moment.hour * 60 + moment.minute) * 60
        + moment.second
    )


def decode_datetime(encoded: int) -> datetime | None:
    """Bongkar format DateTime packed milik device menjadi `datetime`.

    Kebalikan dari `encode_datetime`. Dipakai terutama untuk **membuktikan**
    bahwa encode kita benar (uji bolak-balik) dan untuk membaca nilai DateTime
    yang dilaporkan device.

    Mengembalikan `None` bila nilainya di luar rentang yang masuk akal, alih-alih
    melempar — nilai rusak dari device bukan alasan menggagalkan seluruh request.
    """
    if encoded is None or encoded < 0:
        return None

    seconds_per_day = 24 * 60 * 60
    days, remainder = divmod(int(encoded), seconds_per_day)

    hour, remainder = divmod(remainder, 3600)
    minute, second = divmod(remainder, 60)

    # Device memakai bulan 31 hari dan tahun 12 bulan.
    year_index, day_index = divmod(days, 12 * 31)
    month_index, day_zero_based = divmod(day_index, 31)

    year = 2000 + year_index
    month = month_index + 1
    day = day_zero_based + 1

    try:
        return datetime(year, month, day, hour, minute, second)
    except ValueError:
        return None


# --- Handshake ------------------------------------------------------------

#: Bitmask 10 digit yang memberi tahu device tabel mana yang dikirim ke server.
#: Posisi: 1 AttLog · 2 OpLog · 3 AttPhoto · 4 EnrollUser · 5 ChgUser ·
#:         6 EnrollFP · 7 ChgFP · 8 FPImage · 9 Face · 10 UserPic
#:
#: Posisi 6 dan 7 inilah yang membuat device mengunggah template sidik jari
#: begitu didaftarkan/diubah. Nilai lama `1111000000` (hanya absensi) adalah
#: sebab tidak ada template yang pernah masuk. Default di sini menyalakan
#: 1–7 dan mematikan 8–10: gambar sidik jari, template wajah, dan foto user
#: berukuran besar dan hanya akan membanjiri server.
DEFAULT_TRANS_FLAG = "1111111000"


def handshake_response(
    serial_number: str,
    *,
    op_stamp: int,
    trans_flag: str = DEFAULT_TRANS_FLAG,
    error_delay: int = 60,
    delay: int = 30,
    res_log_day: int = 18250,
    res_log_del_count: int = 10000,
    res_log_count: int = 50000,
    trans_times: str = "00:00;14:05",
    trans_interval: int = 4,
    realtime: int = 1,
    encrypt: int = 0,
) -> str:
    """Susun balasan handshake.

    Tiga hal yang di sini sengaja **tidak dikirim**, dan masing-masing punya
    alasan yang berbeda:

    - **`TimeZone` tidak dikirim sama sekali.** Implementasi referensi dan
      deployment X100C yang jalan sama-sama menghilangkannya. Field ini dulu
      diisi nama IANA (`Asia/Jakarta`) — bentuk yang **salah** untuk field ini.
      Zona tetap diterapkan, tapi saat menafsirkan timestamp absensi
      (lihat `app.iclock.timezones`), bukan lewat handshake.
    - **`Encrypt=0` sengaja**, karena firmware yang dimaksud tidak memakai
      enkripsi payload.
    - **`OpStamp` adalah unix timestamp**, bukan tanggal terformat. Nilai
      terformat pernah dipakai dan membuat device menolak seluruh blok opsi.

    Terminasi baris **wajib CRLF**. Memakai LF saja pernah membuat device diam
    tanpa keluhan apa pun.
    """
    lines = [
        f"GET OPTION FROM: {serial_number}",
        "Stamp=9999",
        f"OpStamp={op_stamp}",
        f"ErrorDelay={error_delay}",
        f"Delay={delay}",
        f"ResLogDay={res_log_day}",
        f"ResLogDelCount={res_log_del_count}",
        f"ResLogCount={res_log_count}",
        f"TransTimes={trans_times}",
        f"TransInterval={trans_interval}",
        f"TransFlag={trans_flag}",
        f"Realtime={realtime}",
        f"Encrypt={encrypt}",
    ]
    return "\r\n".join(lines)


#: Jenis tabel yang dikenali pada query `table=`.
TABLE_ATTLOG = "ATTLOG"
TABLE_OPERLOG = "OPERLOG"
TABLE_USERINFO = "USERINFO"


def table_kind(table: str | None) -> str:
    """Kelompokkan `table=` menjadi kategori yang ditangani berbeda.

    `OPERLOG` pada firmware ini dipakai untuk unggahan user/biometrik, dan
    `OPLOG` adalah ejaan alternatif yang juga muncul di lapangan.
    """
    normalized = (table or "").strip().upper()
    if normalized in {"OPERLOG", "OPLOG"}:
        return "biometric"
    if normalized == TABLE_USERINFO:
        return "userinfo"
    return "attendance"
