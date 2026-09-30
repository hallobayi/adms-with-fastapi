"""Penerapan zona waktu pada timestamp device (keputusan #4, SCHEMA §16).

**Masalahnya:** device X100C mengirim waktu **dinding lokal**, mis.
`2026-09-29 08:15:03`, tanpa penanda zona. Device tidak mengirim UTC. Baris itu
ambigu — `08:15` di WIB dan `08:15` di WITA adalah momen berbeda.

**Kenapa berbahaya:** salah menafsirkan tidak memunculkan error. Datanya tetap
"terlihat masuk", hanya bergeser beberapa jam. Karena itu konversi dilakukan
di **satu tempat** (modul ini) dan hasilnya selalu disimpan bersama jejaknya.

**Aturan penerapan 3 tingkat (berhenti di yang pertama cocok):**

1. `device.tz_name` — normal
2. zona default server (`settings.default_tz_name`) — device belum punya zona
3. `UTC` — cadangan terakhir

Tingkat 2 dan 3 **wajib** tercatat sebagai anomali: artinya ada device yang
zonanya belum dikonfigurasi dengan benar.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger(__name__)

UTC = timezone.utc

#: Nama alias yang sering dipakai di lapangan tetapi bukan nama IANA.
#: Dipetakan agar input admin yang "hampir benar" tidak langsung jatuh ke UTC.
_ALIASES = {
    "wib": "Asia/Jakarta",
    "wita": "Asia/Makassar",
    "wit": "Asia/Jayapura",
    "jakarta": "Asia/Jakarta",
    "jkt": "Asia/Jakarta",
    "utc+7": "Asia/Jakarta",
    "gmt+7": "Asia/Jakarta",
    "utc+8": "Asia/Makassar",
    "utc+9": "Asia/Jayapura",
}


@dataclass(frozen=True)
class ResolvedZone:
    """Zona yang akhirnya dipakai, beserta dari mana asalnya."""

    name: str
    source: str  # 'device' | 'server_default' | 'fallback_utc' | 'invalid_input'

    @property
    def is_fallback(self) -> bool:
        """True bila zona ini bukan dari konfigurasi device yang sah."""
        return self.source != "device"


def is_valid_zone(name: str | None) -> bool:
    """Cek apakah `name` bisa dipakai sebagai nama zona."""
    if not name:
        return False
    candidate = _normalize(name)
    try:
        ZoneInfo(candidate)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return False
    return True


def _normalize(name: str) -> str:
    stripped = name.strip()
    return _ALIASES.get(stripped.lower(), stripped)


def resolve_zone(
    device_tz: str | None,
    default_tz: str | None = None,
) -> ResolvedZone:
    """Tentukan zona yang dipakai untuk memparse punch dari satu device.

    Urutan: `device_tz` → `default_tz` → UTC. Tingkat 2 dan 3 dilaporkan lewat
    `ResolvedZone.is_fallback` supaya pemanggil bisa mencatatnya sebagai
    anomali (dan tidak diam-diam memakai UTC untuk seluruh perusahaan).
    """
    for candidate, source in ((device_tz, "device"), (default_tz, "server_default")):
        if not candidate:
            continue
        normalized = _normalize(candidate)
        try:
            ZoneInfo(normalized)
        except (ZoneInfoNotFoundError, ValueError, KeyError):
            logger.warning(
                "Zona %r (dari %s) tidak dikenali; mencoba tingkat berikutnya",
                candidate,
                source,
            )
            continue
        return ResolvedZone(name=normalized, source=source)

    return ResolvedZone(name="UTC", source="fallback_utc")


def to_utc(local_wall_clock: datetime, zone_name: str) -> datetime:
    """Ubah waktu dinding lokal menjadi waktu UTC (naive, siap disimpan MySQL).

    Hasilnya **naive** dengan sengaja: kolom MySQL `DATETIME` tidak menyimpan
    offset, dan menyimpan nilai aware hanya akan membuat offsetnya dibuang
    diam-diam sambil memberi kesan sebaliknya.
    """
    naive = local_wall_clock.replace(tzinfo=None)

    if zone_name == "UTC":
        return naive

    try:
        zone = ZoneInfo(zone_name)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        logger.warning("Zona %r tidak dikenal saat konversi; memakai UTC", zone_name)
        return naive

    localized = naive.replace(tzinfo=zone)
    return localized.astimezone(UTC).replace(tzinfo=None)


def zone_offset_minutes(zone_name: str, moment: datetime | None = None) -> int | None:
    """Hitung offset menit sebuah zona pada satu momen.

    Dipakai untuk mengisi `device.tz_offset_minutes` (cache) dan untuk
    memetakan ke jam bulat saat membentuk balasan handshake.
    """
    try:
        zone = ZoneInfo(zone_name)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return None

    reference = (moment or datetime.now(UTC)).replace(tzinfo=UTC)
    offset = reference.astimezone(zone).utcoffset()
    if offset is None:
        return None
    return int(offset.total_seconds() // 60)


def handshake_hour_offset(zone_name: str, moment: datetime | None = None) -> int:
    """Offset **jam** bulat untuk field `TimeZone=` handshake.

    Protokol handshake ZKTeco memakai offset jam bilangan bulat, bukan nama
    IANA. Zona dengan offset pecahan (mis. `Asia/Kathmandu`, +05:45) tidak bisa
    diwakili persis — di situ handshake memakai pembulatan, tetapi **parse
    wajib memakai `tz_name` yang tepat**, bukan ikut pembulatan.
    """
    minutes = zone_offset_minutes(zone_name, moment)
    if minutes is None:
        return 0
    return round(minutes / 60)


def shift_by_offset(wall_clock: datetime, offset_minutes: int) -> datetime:
    """Geser waktu dinding lokal ke UTC memakai offset tetap.

    Alternatif aritmetika untuk kasus sederhana (Indonesia tidak memakai DST),
    dipakai bila basis data zona MySQL belum dimuat sehingga `CONVERT_TZ`
    mengembalikan NULL. **Bukan** pengganti nama IANA: begitu ada device di
    yurisdiksi ber-DST, cara ini akan salah.
    """
    return wall_clock.replace(tzinfo=None) - timedelta(minutes=offset_minutes)
