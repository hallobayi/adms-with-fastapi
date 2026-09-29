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
    )
    return Settings(
        app_name=os.getenv("APP_NAME", "ADMS"),
        debug=_get_bool("DEBUG", default=False),
        database=database,
    )
