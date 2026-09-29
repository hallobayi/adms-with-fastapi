"""Uji rute kesehatan dan konfigurasi."""

from __future__ import annotations

from app import database
from app.config import get_settings


def test_health_reports_degraded_when_db_down(client, monkeypatch):
    """Tanpa MySQL, endpoint tetap 200 tapi menandai database degraded."""
    monkeypatch.setattr(database, "ping", lambda: False)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "degraded"}


def test_health_reports_ok_when_db_up(client, monkeypatch):
    monkeypatch.setattr(database, "ping", lambda: True)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_settings_are_cached():
    """get_settings() harus mengembalikan objek yang sama."""
    assert get_settings() is get_settings()


def test_settings_read_env():
    settings = get_settings()
    assert settings.database.host == "localhost"
    assert settings.database.dbname == "adms_test"
    assert settings.debug is True


def test_docs_available_in_debug(client):
    """DEBUG=true membuka /docs dan /openapi.json."""
    assert client.get("/openapi.json").status_code == 200
