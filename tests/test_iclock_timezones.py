"""Uji penerapan zona waktu (keputusan #4).

Bug zona waktu adalah jenis yang paling mahal: tidak ada error, data tetap
"terlihat masuk", hanya bergeser beberapa jam. Karena itu konversinya diuji
eksplisit, termasuk kasus pergantian hari.
"""

from __future__ import annotations

from datetime import datetime

from app.iclock import timezones


def test_resolve_zone_memakai_zona_device() -> None:
    zone = timezones.resolve_zone("Asia/Jakarta", "UTC")

    assert zone.name == "Asia/Jakarta"
    assert zone.source == "device"
    assert not zone.is_fallback


def test_resolve_zone_jatuh_ke_default_server() -> None:
    zone = timezones.resolve_zone(None, "Asia/Makassar")

    assert zone.name == "Asia/Makassar"
    assert zone.source == "server_default"
    assert zone.is_fallback


def test_resolve_zone_cadangan_terakhir_utc() -> None:
    zone = timezones.resolve_zone(None, None)

    assert zone.name == "UTC"
    assert zone.source == "fallback_utc"
    assert zone.is_fallback


def test_resolve_zone_menerima_alias_wib() -> None:
    """Input admin yang "hampir benar" tidak langsung jatuh ke UTC."""
    zone = timezones.resolve_zone("WIB", None)

    assert zone.name == "Asia/Jakarta"
    assert zone.source == "device"


def test_resolve_zone_nama_tidak_valid_jatuh_ke_berikutnya() -> None:
    zone = timezones.resolve_zone("Bukan/Zona", "Asia/Jakarta")

    assert zone.name == "Asia/Jakarta"
    assert zone.source == "server_default"


def test_is_valid_zone() -> None:
    assert timezones.is_valid_zone("Asia/Jakarta")
    assert timezones.is_valid_zone("WIB")
    assert not timezones.is_valid_zone("Bukan/Zona")
    assert not timezones.is_valid_zone("")
    assert not timezones.is_valid_zone(None)


def test_to_utc_wib_menggeser_tujuh_jam() -> None:
    """WIB = UTC+7, jadi 08:00 lokal adalah 01:00 UTC hari yang sama."""
    result = timezones.to_utc(datetime(2026, 9, 29, 8, 0, 0), "Asia/Jakarta")

    assert result == datetime(2026, 9, 29, 1, 0, 0)


def test_to_utc_punch_pagi_melintasi_hari() -> None:
    """Punch 06:00 WIB adalah 23:00 UTC hari SEBELUMNYA.

    Inilah kasus yang membuat `punch_date` wajib diambil dari waktu lokal:
    memakai tanggal UTC akan memasukkan punch pagi ke hari kerja yang salah.
    """
    local = datetime(2026, 9, 29, 6, 0, 0)
    result = timezones.to_utc(local, "Asia/Jakarta")

    assert result == datetime(2026, 9, 28, 23, 0, 0)
    assert result.date() != local.date(), "tanggal UTC memang berbeda dari lokal"


def test_to_utc_hasil_naive() -> None:
    """Hasilnya harus naive: kolom MySQL DATETIME tidak menyimpan offset.

    Mengembalikan nilai aware akan membuat offsetnya dibuang diam-diam sambil
    memberi kesan sebaliknya.
    """
    result = timezones.to_utc(datetime(2026, 9, 29, 8, 0, 0), "Asia/Jakarta")

    assert result.tzinfo is None


def test_to_utc_zona_utc_tidak_berubah() -> None:
    local = datetime(2026, 9, 29, 8, 0, 0)

    assert timezones.to_utc(local, "UTC") == local


def test_to_utc_zona_tidak_dikenal_tidak_melempar() -> None:
    """Zona rusak tidak boleh menggagalkan ingest seluruh batch."""
    local = datetime(2026, 9, 29, 8, 0, 0)

    assert timezones.to_utc(local, "Bukan/Zona") == local


def test_zone_offset_minutes_wib() -> None:
    assert timezones.zone_offset_minutes("Asia/Jakarta") == 420


def test_zone_offset_minutes_wita_dan_wit() -> None:
    assert timezones.zone_offset_minutes("Asia/Makassar") == 480
    assert timezones.zone_offset_minutes("Asia/Jayapura") == 540


def test_handshake_hour_offset_wib() -> None:
    assert timezones.handshake_hour_offset("Asia/Jakarta") == 7


def test_handshake_hour_offset_zona_pecahan_dibulatkan() -> None:
    """Kathmandu +05:45 tidak bisa diwakili jam bulat; dibulatkan.

    Ini justru alasan parse **wajib** memakai `tz_name` yang tepat dan tidak
    ikut pembulatan handshake.
    """
    assert timezones.handshake_hour_offset("Asia/Kathmandu") == 6


def test_shift_by_offset_sama_dengan_konversi_zona() -> None:
    """Aritmetika offset tetap harus sepakat dengan konversi zona IANA.

    Indonesia tidak memakai DST, jadi keduanya harus memberi hasil identik —
    kalau tidak, ada yang salah di salah satunya.
    """
    local = datetime(2026, 9, 29, 6, 0, 0)

    assert timezones.shift_by_offset(local, 420) == timezones.to_utc(local, "Asia/Jakarta")
