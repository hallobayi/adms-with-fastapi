"""Fixture bersama untuk pengujian."""

from __future__ import annotations

import os

import pytest

# Environment uji diisi sebelum modul aplikasi diimpor, karena
# `app.config.get_settings()` memvalidasi variabel wajib saat dipanggil.
os.environ.setdefault("MYSQL_HOST", "localhost")
os.environ.setdefault("MYSQL_USER", "tester")
os.environ.setdefault("MYSQL_PASSWORD", "secret")
os.environ.setdefault("MYSQL_DB", "adms_test")
os.environ.setdefault("DEBUG", "true")

from fastapi.testclient import TestClient  # noqa: E402

from app.application import create_app  # noqa: E402


@pytest.fixture()
def client() -> TestClient:
    """Klien HTTP yang menguji aplikasi tanpa menjalankan server."""
    return TestClient(create_app())
