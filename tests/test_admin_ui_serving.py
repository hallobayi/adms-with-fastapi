"""Pengujian penyajian SPA admin dari FastAPI (`/admin`).

Yang dijaga di sini adalah hal-hal yang **tidak** muncul sebagai galat saat
salah, melainkan sebagai halaman kosong: prefiks yang tidak cocok, berkas aset
yang tidak tersaji, dan rute sisi klien yang menghasilkan 404 saat di-refresh.
Semuanya hanya terlihat di browser, jadi tanpa pengujian ini regresinya baru
ketahuan setelah dipakai.

Kasus terakhir — penjagaan `../` — diuji dengan jalur **ter-encode** (`%2e%2e`)
supaya klien HTTP tidak menormalkannya lebih dulu; kalau dinormalkan di sisi
klien, permintaannya tidak pernah sampai ke handler dan pengujiannya tidak
membuktikan apa pun.
"""

from __future__ import annotations

import dataclasses
import logging

import pytest
from fastapi.testclient import TestClient

from app.application import create_app
from app.config import get_settings

INDEX_HTML = "<!doctype html><html><body><div id=root></div></body></html>"
ASSET_JS = "console.log('adms admin');"


@pytest.fixture()
def dist_dir(tmp_path):
    """Bangun tiruan `frontend/dist` berisi index.html dan satu aset."""
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    (dist / "assets" / "app.js").write_text(ASSET_JS, encoding="utf-8")
    return dist


def _client_for(dist) -> TestClient:
    settings = dataclasses.replace(get_settings(), serve_ui=True, frontend_dist=str(dist))
    return TestClient(create_app(settings))


def test_index_disajikan_di_akar_ui(dist_dir):
    response = _client_for(dist_dir).get("/admin")
    assert response.status_code == 200
    assert "<div id=root>" in response.text


def test_rute_sisi_klien_jatuh_ke_index(dist_dir):
    """`/admin/devices` hanya ada di router klien; refresh tidak boleh 404."""
    response = _client_for(dist_dir).get("/admin/devices")
    assert response.status_code == 200
    assert response.text == INDEX_HTML


def test_rute_bersarang_jatuh_ke_index(dist_dir):
    response = _client_for(dist_dir).get("/admin/conflicts/12/edit")
    assert response.status_code == 200
    assert response.text == INDEX_HTML


def test_aset_disajikan_apa_adanya(dist_dir):
    response = _client_for(dist_dir).get("/admin/assets/app.js")
    assert response.status_code == 200
    assert response.text == ASSET_JS


def test_berkas_lain_di_dalam_dist_ikut_disajikan(dist_dir):
    """Berkas di luar `assets/` (mis. favicon) tetap harus bisa diambil."""
    (dist_dir / "favicon.ico").write_bytes(b"\x00\x01")
    response = _client_for(dist_dir).get("/admin/favicon.ico")
    assert response.status_code == 200
    assert response.content == b"\x00\x01"


def test_traversal_tidak_membocorkan_berkas_luar(dist_dir, tmp_path):
    """`../` tidak boleh dipakai membaca berkas di luar direktori build."""
    rahasia = tmp_path / "rahasia.txt"
    rahasia.write_text("JANGAN SAMPAI TERBACA", encoding="utf-8")

    client = _client_for(dist_dir)
    for jalur in ("/admin/%2e%2e/rahasia.txt", "/admin/%2e%2e%2f%2e%2e%2frahasia.txt"):
        response = client.get(jalur)
        assert "JANGAN SAMPAI TERBACA" not in response.text, jalur
        # Yang benar: jatuh kembali ke index, bukan membocorkan berkas.
        assert response.text == INDEX_HTML, jalur


def test_ui_tidak_dipasang_saat_serve_ui_mati(dist_dir):
    settings = dataclasses.replace(get_settings(), serve_ui=False, frontend_dist=str(dist_dir))
    assert TestClient(create_app(settings)).get("/admin").status_code == 404


def test_dist_belum_dibangun_hanya_memberi_peringatan(tmp_path, caplog):
    """Dist yang tidak ada tidak boleh menggagalkan start server."""
    kosong = tmp_path / "belum-dibangun"
    settings = dataclasses.replace(get_settings(), serve_ui=True, frontend_dist=str(kosong))

    with caplog.at_level(logging.WARNING, logger="app.application"):
        app = create_app(settings)

    assert any("UI tidak dipasang" in record.message for record in caplog.records)
    assert TestClient(app).get("/admin").status_code == 404
    # API tetap hidup — device bergantung padanya.
    assert TestClient(app).get("/health").status_code in (200, 503)


def test_rute_api_tidak_tertutup_catch_all(dist_dir):
    """Catch-all `/admin/{path}` tidak boleh menelan rute `/api/admin/*`."""
    client = _client_for(dist_dir)
    # Tanpa sesi, jawabannya 401 dari dependency — bukan 200 berisi HTML.
    response = client.get("/api/admin/auth/me")
    assert response.status_code == 401
    assert "text/html" not in response.headers.get("content-type", "")


def test_admin_ui_tidak_masuk_skema_openapi(dist_dir):
    """UI bukan bagian dari kontrak API, jadi tidak boleh muncul di /openapi.json."""
    skema = _client_for(dist_dir).get("/openapi.json").json()
    assert not any(path.startswith("/admin") and not path.startswith("/api/") for path in skema["paths"])
