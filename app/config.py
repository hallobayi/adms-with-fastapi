"""Pusat konfigurasi aplikasi ADMS.

Semua pembacaan environment variable terjadi di sini supaya tidak ada
`os.getenv()` yang tersebar di banyak modul. Modul lain cukup mengimpor
objek `settings`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

# Dipanggil sekali saat modul diimpor. Nilai yang sudah ada di environment
# (mis. dari Docker/systemd) tidak akan ditimpa oleh file .env.
load_dotenv()


class ConfigError(RuntimeError):
    """Konfigurasi wajib belum diisi dengan benar."""


def _require(name: str) -> str:
    """Ambil environment variable wajib, gagal cepat bila kosong."""
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigError(
            f"Environment variable {name!r} belum diisi. "
            "Salin env.example menjadi .env lalu lengkapi nilainya."
        )
    return value


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class DatabaseSettings:
    """Detail koneksi MySQL."""

    host: str
    user: str
    password: str
    dbname: str
    port: int = 3306
    connect_timeout: int = 10
    pool_size: int = 10

    def as_kwargs(self) -> dict[str, object]:
        """Parameter siap pakai untuk `mysql.connector.connect(...)`."""
        return {
            "host": self.host,
            "user": self.user,
            "password": self.password,
            "database": self.dbname,
            "port": self.port,
            "connect_timeout": self.connect_timeout,
        }


@dataclass(frozen=True)
class Settings:
    """Konfigurasi aplikasi yang dipakai lintas modul."""

    app_name: str
    debug: bool
    database: DatabaseSettings
    default_tz_name: str = "Asia/Jakarta"
    #: Level log aplikasi (`DEBUG`, `INFO`, `WARNING`, ...). Dipasang sekali di
    #: `create_app()`; lihat `app/logger.py`. Dipisah dari `debug` dengan
    #: sengaja: `DEBUG=true` membuka /docs dan pesan error detail, dan di
    #: produksi kita mungkin ingin log `DEBUG` tanpa membukanya ke publik.
    log_level: str = "INFO"
    #: Sajikan SPA admin (`frontend/dist`) di `/admin`. Bila berkasnya belum
    #: dibangun, aplikasi tetap jalan dan hanya mencatat peringatan — jadi
    #: mengaktifkannya secara default tidak pernah membuat server gagal start.
    serve_ui: bool = True
    #: Lokasi hasil build SPA, relatif terhadap direktori kerja.
    frontend_dist: str = "frontend/dist"

    @property
    def docs_url(self) -> str | None:
        return "/docs" if self.debug else None

    @property
    def redoc_url(self) -> str | None:
        return "/redoc" if self.debug else None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Muat konfigurasi sekali lalu simpan di cache.

    `lru_cache` dipakai agar validasi environment hanya berjalan sekali dan
    objek yang sama dipakai ulang oleh seluruh request.
    """
    database = DatabaseSettings(
        host=_require("MYSQL_HOST"),
        user=_require("MYSQL_USER"),
        password=_require("MYSQL_PASSWORD"),
        dbname=_require("MYSQL_DB"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        connect_timeout=int(os.getenv("MYSQL_CONNECT_TIMEOUT", "10")),
        # Ukuran pool menentukan berapa banyak device bisa diproses bersamaan.
        # Dinaikkan dari angka lama (5) seiring handler iClock dipindah ke
        # worker thread; lihat `app/database.py`.
        pool_size=max(1, int(os.getenv("MYSQL_POOL_SIZE", "10"))),
    )
    return Settings(
        app_name=os.getenv("APP_NAME", "ADMS"),
        debug=_get_bool("DEBUG", default=False),
        database=database,
        # Zona cadangan bila device belum punya `tz_name`. Dipakai saat parse
        # ATTLOG (lihat app/iclock/timezones.py); bukan sekadar tampilan.
        default_tz_name=os.getenv("DEFAULT_TZ_NAME", "Asia/Jakarta").strip()
        or "Asia/Jakarta",
        log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO",
        serve_ui=_get_bool("SERVE_UI", default=True),
        frontend_dist=os.getenv("FRONTEND_DIST", "frontend/dist").strip()
        or "frontend/dist",
    )
