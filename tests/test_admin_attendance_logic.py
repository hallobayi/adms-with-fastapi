"""Uji perhitungan selisih shift & normalisasi hari kerja.

Kedua fungsi ini murni (tanpa database), dan keduanya pernah punya bug nyata
yang ditemukan lewat verifikasi MySQL:

1. **`_compute_shift_deltas` menerima jam UTC.** Karena modul memakai
   `MIN(punch_at)` (UTC) padahal `shift.start_time` adalah jam dinding
   setempat, punch 01:45 UTC yang seharusnya "telat 30 menit" terbaca
   "telat 1000 menit". Uji di bawah menegaskan fungsi ini bekerja pada jam
   dinding — dan uji e2e-lah yang memastikan pemanggilnya mengirim jam lokal.
2. **`work_days_list` menerima `set` dari MySQL.** Kolom `SET` dikembalikan
   driver sebagai `set` Python, dan `str(set)` pernah lolos ke respons API
   sebagai `"{'MO', 'TU'}"`. Uji ini menjaga bentuknya tetap daftar terurut.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from app.admin.helpers import work_days_list
from app.admin.queries_attendance import _compute_shift_deltas

WORK_DATE = date(2026, 9, 28)  # Senin


def _shift(
    start: str = "08:00:00",
    end: str = "17:00:00",
    late_tol: int = 15,
    early_tol: int = 10,
    overnight: bool = False,
) -> dict[str, object]:
    from datetime import timedelta

    def t(value: str) -> timedelta:
        h, m, s = (int(x) for x in value.split(":"))
        return timedelta(hours=h, minutes=m, seconds=s)

    return {
        "start_time": t(start),
        "end_time": t(end),
        "late_tolerance_min": late_tol,
        "early_leave_tol_min": early_tol,
        "is_overnight": overnight,
    }


# --- Selisih shift (jam dinding lokal) ------------------------------------


def test_telat_dihitung_dari_jam_dinding_lokal() -> None:
    """08:45 vs shift 08:00 toleransi 15 -> telat 30 menit.

    Inilah kasus yang dulu rusak: pemanggil mengirim 01:45 (UTC) sehingga
    hasilnya 1000 menit.
    """
    late, early, overtime = _compute_shift_deltas(
        work_date=WORK_DATE,
        first_in=datetime(2026, 9, 28, 8, 45),
        last_out=datetime(2026, 9, 28, 17, 10),
        shift=_shift(),
    )

    assert late == 30
    assert early == 0
    assert overtime == 10


def test_masuk_tepat_waktu_tidak_telat() -> None:
    late, early, overtime = _compute_shift_deltas(
        work_date=WORK_DATE,
        first_in=datetime(2026, 9, 28, 7, 55),
        last_out=datetime(2026, 9, 28, 17, 5),
        shift=_shift(),
    )

    assert late == 0
    assert early == 0
    assert overtime == 5


def test_toleransi_menyerap_keterlambatan_kecil() -> None:
    """Telat 10 menit dengan toleransi 15 -> 0, bukan 10."""
    late, _, _ = _compute_shift_deltas(
        work_date=WORK_DATE,
        first_in=datetime(2026, 9, 28, 8, 10),
        last_out=datetime(2026, 9, 28, 17, 0),
        shift=_shift(),
    )

    assert late == 0


def test_pulang_cepat_dihitung_setelah_toleransi() -> None:
    """Pulang 16:50 vs 17:00, toleransi 10 -> 0. Pulang 16:30 -> 20."""
    _, early0, _ = _compute_shift_deltas(
        work_date=WORK_DATE,
        first_in=datetime(2026, 9, 28, 8, 0),
        last_out=datetime(2026, 9, 28, 16, 50),
        shift=_shift(),
    )
    _, early20, _ = _compute_shift_deltas(
        work_date=WORK_DATE,
        first_in=datetime(2026, 9, 28, 8, 0),
        last_out=datetime(2026, 9, 28, 16, 30),
        shift=_shift(),
    )

    assert early0 == 0
    assert early20 == 20


def test_shift_malam_pulang_lewat_tengah_malam() -> None:
    """Shift 20:00-05:00: masuk 20:05, pulang 05:10 keesokan harinya.

    Punch pulang berada di hari kalender berikutnya; tanpa penanganan khusus
    selisihnya jadi negatif dan seluruh hasilnya salah.
    """
    late, early, overtime = _compute_shift_deltas(
        work_date=WORK_DATE,
        first_in=datetime(2026, 9, 28, 20, 5),
        last_out=datetime(2026, 9, 29, 5, 10),
        shift=_shift(start="20:00:00", end="05:00:00", late_tol=10, early_tol=10, overnight=True),
    )

    assert late == 0     # 5 menit, di dalam toleransi 10
    assert early == 0    # pulang 05:10, lewat dari 05:00
    assert overtime == 10


def test_batas_toleransi_tepat_sama() -> None:
    """Telat tepat 15 menit dengan toleransi 15 -> 0 (batas inklusif)."""
    late, _, _ = _compute_shift_deltas(
        work_date=WORK_DATE,
        first_in=datetime(2026, 9, 28, 8, 15),
        last_out=datetime(2026, 9, 28, 17, 0),
        shift=_shift(),
    )

    assert late == 0


def test_selisih_tidak_pernah_negatif() -> None:
    """Masuk lebih awal & pulang lebih lambat tidak boleh menghasilkan negatif."""
    late, early, overtime = _compute_shift_deltas(
        work_date=WORK_DATE,
        first_in=datetime(2026, 9, 28, 6, 0),
        last_out=datetime(2026, 9, 28, 23, 0),
        shift=_shift(),
    )

    assert late == 0
    assert early == 0
    assert overtime == 360


def test_selisih_bertipe_int_bukan_float() -> None:
    late, early, overtime = _compute_shift_deltas(
        work_date=WORK_DATE,
        first_in=datetime(2026, 9, 28, 8, 45, 30),
        last_out=datetime(2026, 9, 28, 17, 10, 45),
        shift=_shift(),
    )

    assert all(isinstance(v, int) for v in (late, early, overtime))


# --- Normalisasi hari kerja -----------------------------------------------


@pytest.mark.parametrize(
    "masukan,harapan",
    [
        ({"MO", "TU", "WE"}, ["MO", "TU", "WE"]),
        ({"WE", "MO", "TU"}, ["MO", "TU", "WE"]),          # diurutkan kanonik
        ("MO,TU,WE", ["MO", "TU", "WE"]),
        ("WE,MO,TU", ["MO", "TU", "WE"]),
        (frozenset({"FR", "SA", "SU"}), ["FR", "SA", "SU"]),
        (["SA", "SU"], ["SA", "SU"]),
        ("MO, MO, TU", ["MO", "TU"]),                       # duplikat dibuang
        (" mo , tu ", ["MO", "TU"]),                        # spasi & huruf kecil
        (None, []),
        ("", []),
        ("XX,YY", []),                                      # nilai tak dikenal
    ],
)
def test_work_days_dinormalkan_ke_daftar_terurut(masukan: object, harapan: list[str]) -> None:
    """MySQL mengembalikan kolom `SET` sebagai `set` Python; jangan bocorkan
    bentuk itu ke API."""
    assert work_days_list(masukan) == harapan


def test_work_days_bukan_repr_set() -> None:
    """Regresi: pernah keluar sebagai \"{'MO', 'TU'}\" di respons JSON."""
    hasil = work_days_list({"MO", "TU", "WE"})

    assert isinstance(hasil, list)
    assert all(isinstance(d, str) and "{" not in d and "'" not in d for d in hasil)
