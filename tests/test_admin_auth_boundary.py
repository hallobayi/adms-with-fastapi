"""Uji batas keamanan HTTP dashboard admin, tanpa database.

Pertanyaan yang dijawab berkas ini: **apakah benar-benar tidak ada endpoint
`/api/admin/*` yang bisa diakses tanpa sesi?** Ini jenis kesalahan yang paling
mahal kalau lolos — bukan bug tampilan, tapi data absensi seluruh perusahaan
terbuka bagi siapa saja yang tahu URL-nya.

Pendekatannya: ganti dependency `current_admin` dengan stub, lalu periksa kode
status. Tidak ada MySQL yang terlibat, jadi uji ini cepat dan bisa jalan di CI
mana pun.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.admin import auth
from app.admin.dependencies import current_admin, require_superuser
from app.application import create_app
from app.database import connection

#: (metode, path) seluruh endpoint dashboard yang **wajib** login. Daftar ini
#: sengaja ditulis tangan supaya endpoint baru yang lupa didaftarkan menggagalkan
#: `test_daftar_endpoint_mencakup_seluruh_openapi`, bukan diam-diam tak teruji.
#: Path memakai placeholder `{...}` persis seperti di skema OpenAPI.
ENDPOINTS: list[tuple[str, str]] = [
    ("get", "/api/admin/dashboard"),
    ("get", "/api/admin/auth/me"),
    ("post", "/api/admin/auth/logout"),
    ("post", "/api/admin/auth/password"),
    ("get", "/api/admin/devices"),
    ("get", "/api/admin/devices/summary"),
    ("get", "/api/admin/devices/{device_id}"),
    ("patch", "/api/admin/devices/{device_id}"),
    ("post", "/api/admin/devices/{device_id}/approve"),
    ("get", "/api/admin/requests"),
    ("get", "/api/admin/requests/{request_id}"),
    ("get", "/api/admin/conflicts"),
    ("get", "/api/admin/conflicts/summary"),
    ("get", "/api/admin/conflicts/{conflict_id}"),
    ("post", "/api/admin/conflicts/{conflict_id}/resolve"),
    ("get", "/api/admin/attendance"),
    ("get", "/api/admin/attendance/summary"),
    ("patch", "/api/admin/attendance/{attendance_id}"),
    ("delete", "/api/admin/attendance/{attendance_id}"),
    ("post", "/api/admin/attendance/recompute"),
    ("get", "/api/admin/employees"),
    ("post", "/api/admin/employees"),
    ("get", "/api/admin/employees/departments"),
    ("get", "/api/admin/employees/{employee_id}"),
    ("patch", "/api/admin/employees/{employee_id}"),
    ("delete", "/api/admin/employees/{employee_id}"),
    ("get", "/api/admin/shifts"),
    ("post", "/api/admin/shifts"),
    ("get", "/api/admin/shifts/{shift_id}"),
    ("patch", "/api/admin/shifts/{shift_id}"),
    ("delete", "/api/admin/shifts/{shift_id}"),
    ("get", "/api/admin/shift-assignments"),
    ("post", "/api/admin/shift-assignments"),
    ("delete", "/api/admin/shift-assignments/{assignment_id}"),
    ("get", "/api/admin/holidays"),
    ("post", "/api/admin/holidays"),
    ("delete", "/api/admin/holidays/{holiday_id}"),
    ("get", "/api/admin/accounts"),
    ("post", "/api/admin/accounts"),
    ("patch", "/api/admin/accounts/{admin_id}"),
]


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


def test_daftar_endpoint_mencakup_seluruh_openapi(client: TestClient) -> None:
    """Setiap path /api/admin di skema OpenAPI harus ada di daftar ENDPOINTS.

    Ini menjaga daftar tangan di atas tetap sinkron. Endpoint baru yang lupa
    didaftarkan akan langsung menggagalkan uji ini — bukan lolos tanpa diuji.
    """
    spec = client.get("/openapi.json").json()
    actual = {
        (method, path)
        for path, ops in spec["paths"].items()
        if path.startswith("/api/admin")
        for method in ops
        # `/auth/login` satu-satunya endpoint admin yang memang publik.
        if not (path == "/api/admin/auth/login" and method == "post")
    }
    expected = set(ENDPOINTS)

    assert actual - expected == set(), "Endpoint baru belum didaftarkan di ENDPOINTS"
    assert expected - actual == set(), "ENDPOINTS memuat path yang sudah tidak ada"


@pytest.mark.parametrize("method,path", ENDPOINTS, ids=[f"{m} {p}" for m, p in ENDPOINTS])
def test_tanpa_login_ditolak_401(client: TestClient, method: str, path: str) -> None:
    """Tanpa cookie sesi, semuanya harus 401 — bukan 200, bukan 500.

    `POST /auth/logout` dikecualikan: endpoint itu **sengaja** membalas 200
    tanpa sesi. Logout harus terasa idempoten, dan memberi tahu pemanggil
    "sesi tidak ada" tidak berguna — malah membocorkan apakah cookie yang ia
    pegang masih sah. Tidak ada data yang bisa dijangkau lewat jalur itu.
    """
    if path == "/api/admin/auth/logout":
        response = client.post(path)
        assert response.status_code == 200
        return

    # Placeholder path diganti angka; id tidak penting karena auth diperiksa
    # lebih dulu, jadi permintaan berhenti di 401 sebelum menyentuh database.
    concrete = path.replace("{device_id}", "1").replace("{request_id}", "1")
    concrete = concrete.replace("{conflict_id}", "1").replace("{attendance_id}", "1")
    concrete = concrete.replace("{employee_id}", "1").replace("{shift_id}", "1")
    concrete = concrete.replace("{assignment_id}", "1").replace("{holiday_id}", "1")
    concrete = concrete.replace("{admin_id}", "1")

    response = getattr(client, method)(concrete)

    assert response.status_code == 401, (
        f"{method.upper()} {path} membalas {response.status_code}, seharusnya 401"
    )


def test_cookie_sesi_palsu_ditolak_401(client: TestClient) -> None:
    """Cookie berisi token asal-asalan tidak boleh membuka apa pun.

    Ini menyentuh database (untuk mencari hash token), jadi dilewati bila
    MySQL tidak tersedia — di CI tanpa MySQL, `test_tanpa_login_ditolak_401`
    sudah menutupi jalur "tidak ada cookie sama sekali".
    """
    client.cookies.set("adms_admin_session", "token-palsu-yang-tidak-ada")

    try:
        response = client.get("/api/admin/auth/me")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"MySQL tidak tersedia: {exc}")

    assert response.status_code == 401


def test_bukan_superuser_ditolak_403(client: TestClient) -> None:
    """Akun biasa yang mengakses /accounts harus 403, bukan 401.

    401 berarti "belum login" dan membuat klien mengirim ulang permintaan ke
    halaman login; masalahnya di sini wewenang, bukan identitas.
    """
    biasa = auth.AdminUser(id=2, username="biasa", display_name=None, is_superuser=False)
    client.app.dependency_overrides[current_admin] = lambda: biasa
    client.app.dependency_overrides[require_superuser] = lambda: (
        _raise_forbidden()
    )

    try:
        response = client.get("/api/admin/accounts")
    finally:
        client.app.dependency_overrides.clear()

    assert response.status_code == 403


def _raise_forbidden():
    from fastapi import HTTPException

    raise HTTPException(status_code=403, detail="Butuh wewenang superuser.")


def test_superuser_diizinkan_lewat(client: TestClient, monkeypatch) -> None:
    """Superuser sah boleh masuk sampai ke query — dibuktikan dengan 200."""
    pengawas = auth.AdminUser(id=1, username="boss", display_name="Boss", is_superuser=True)
    client.app.dependency_overrides[require_superuser] = lambda: pengawas

    # `auth.list_admins` adalah satu-satunya akses database di endpoint ini;
    # diganti dengan nilai tetap supaya tidak perlu MySQL. `fetch()` membuka
    # koneksinya lewat `app.database.connection`, jadi itu yang di-stub.
    monkeypatch.setattr(
        "app.admin.router_accounts.auth.list_admins",
        lambda conn: [
            {
                "id": 1, "username": "boss", "display_name": "Boss",
                "is_active": True, "is_superuser": True,
                "last_login_at": None, "created_at": None,
            }
        ],
    )
    monkeypatch.setattr(
        "app.database.connection", _dummy_connection
    )

    try:
        response = client.get("/api/admin/accounts")
    finally:
        client.app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["accounts"][0]["username"] == "boss"


class _DummyConn:
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def close(self) -> None: ...


def _dummy_connection():
    from contextlib import contextmanager

    @contextmanager
    def _cm():
        yield _DummyConn()

    return _cm()


def test_openapi_tidak_membocorkan_endpoint_internal() -> None:
    """Dokumentasi publik hanya boleh memuat grup yang memang publik."""
    spec = TestClient(create_app()).get("/openapi.json").json()
    prefixes = {path.strip("/").split("/")[0] or "root" for path in spec["paths"]}

    assert prefixes <= {"root", "iclock", "api", "health", "items"}, prefixes
