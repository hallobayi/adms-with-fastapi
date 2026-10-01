"""Konfigurasi logging aplikasi — dipanggil sekali saat aplikasi dibangun.

Sebelum modul ini ada, 18 modul memanggil `logging.getLogger(__name__)` tetapi
**tidak ada satu pun** yang memasang handler. Akibatnya `logger.info(...)` di
jalur ingest dan dashboard tidak pernah muncul: root logger tanpa handler hanya
meneruskan ke `lastResort` (level WARNING) sehingga seluruh log INFO hilang, dan
`DEBUG` — yang justru dipakai untuk mendiagnosis device yang diam — tidak bisa
dinyalakan sama sekali.

Aturan yang dipegang modul ini:

- **Satu handler di root logger.** Semua `logging.getLogger(__name__)` otomatis
  mewarisinya, jadi tidak ada modul yang perlu tahu cara log dikonfigurasi dan
  tidak mungkin ada log yang "lupa dipasangi handler".
- **Idempoten.** `configure_logging()` boleh dipanggil berkali-kali (mis. tiap
  `create_app()` di test) tanpa menumpuk handler ganda — tumpukan handler adalah
  sebab klasik satu baris log tercetak tiga kali.
- **Tanpa dependensi baru.** Pewarnaan memakai escape ANSI bawaan dan hanya
  dinyalakan bila keluarannya benar-benar terminal; log yang dialihkan ke berkas
  atau dibaca tooling tetap bersih dari kode warna.
"""

from __future__ import annotations

import logging
import os
import sys

#: Format dan format waktu untuk seluruh log aplikasi.
LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

#: Level yang dipakai bila `LOG_LEVEL` tidak diisi.
DEFAULT_LEVEL = "INFO"

#: Kode warna ANSI per level. Dipakai hanya pada terminal.
_COLORS = {
    logging.DEBUG: "\033[36m",  # cyan
    logging.INFO: "\033[32m",  # hijau
    logging.WARNING: "\033[33m",  # kuning
    logging.ERROR: "\033[31m",  # merah
    logging.CRITICAL: "\033[35m",  # magenta
}
_RESET = "\033[0m"

#: Logger pihak ketiga yang berisik pada level DEBUG. Dinaikkan ke WARNING
#: supaya log aplikasi tidak tenggelam oleh baris koneksi/driver.
_NOISY_LOGGERS = ("mysql", "mysql.connector", "urllib3", "asyncio")


class _ColorFormatter(logging.Formatter):
    """Formatter yang mewarnai baris berdasarkan levelnya.

    Pewarnaan bersifat kosmetik: `configure_logging` hanya memakai formatter ini
    bila stream-nya terminal, sehingga berkas log tidak pernah berisi escape
    ANSI.
    """

    def format(self, record: logging.LogRecord) -> str:
        message = super().format(record)
        color = _COLORS.get(record.levelno)
        if color is None:
            return message
        return f"{color}{message}{_RESET}"


def _resolve_level(level: int | str | None) -> int:
    """Ubah nama level (`"debug"`, `"INFO"`) menjadi konstanta `logging`.

    Sengaja **tidak** membaca environment sendiri: `LOG_LEVEL` dibaca sekali di
    `app.config` (lihat aturan "tidak ada `os.getenv()` yang tersebar"), lalu
    nilainya diteruskan ke sini lewat `create_app()`.
    """
    if level is None:
        level = DEFAULT_LEVEL

    if isinstance(level, int):
        return level

    resolved = logging.getLevelName(level.strip().upper())
    # `getLevelName` mengembalikan string "Level X" untuk nama yang tidak dikenal.
    if isinstance(resolved, int):
        return resolved
    return logging.INFO


def _use_color(stream: object) -> bool:
    """Apakah stream ini layak diberi warna ANSI.

    `NO_COLOR` dibaca langsung di sini (bukan lewat `app.config`) karena ini
    konvensi terminal, bukan konfigurasi aplikasi: ia mengatur tampilan log di
    mesin yang menjalankannya, bukan perilaku aplikasi.
    """
    if os.getenv("NO_COLOR"):  # https://no-color.org/
        return False
    return bool(getattr(stream, "isatty", lambda: False)())


def configure_logging(level: int | str | None = None) -> None:
    """Pasang handler+format ke root logger. Aman dipanggil berkali-kali.

    Handler lama milik kita sendiri dibuang lebih dulu; handler milik pihak lain
    (mis. `uvicorn` bila dijalankan dengan konfigurasi log sendiri) dibiarkan
    agar tidak mengambil alih kendali yang bukan milik kita.
    """
    resolved = _resolve_level(level)

    stream = sys.stdout
    formatter: logging.Formatter
    if _use_color(stream):
        formatter = _ColorFormatter(LOG_FORMAT, datefmt=DATE_FORMAT)
    else:
        formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    handler = logging.StreamHandler(stream)
    handler.setFormatter(formatter)
    handler.set_name("adms")

    root = logging.getLogger()
    # Buang hanya handler kita dari pemanggilan sebelumnya (idempoten).
    for existing in list(root.handlers):
        if existing.get_name() == "adms":
            root.removeHandler(existing)
    root.addHandler(handler)

    # Root menentukan level bawaan seluruh aplikasi. `NOTSET` membuat logger
    # anak mewarisi level ini.
    root.setLevel(resolved)

    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(max(resolved, logging.WARNING))


def setup_logger(
    name: str | None = None, level: int | str | None = None
) -> logging.Logger:
    """Pastikan logging terkonfigurasi, lalu kembalikan logger bernama.

    Bentuk ini mengikuti kebiasaan starter `fastapi-react-starter`
    (`setup_logger(...)` di titik masuk) tetapi sengaja tidak memasang handler
    per-logger: cukup root yang dipasangi sekali, sisanya mewarisi.
    """
    configure_logging(level)
    return logging.getLogger(name)


__all__ = [
    "DEFAULT_LEVEL",
    "LOG_FORMAT",
    "configure_logging",
    "setup_logger",
]
