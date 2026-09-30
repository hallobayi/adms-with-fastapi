"""Uji lapisan keamanan dashboard admin: hashing password & token sesi.

Tidak ada database di sini — `app.admin.security` murni fungsi, dan justru itu
yang perlu diuji terpisah: aturan keamanannya harus tetap benar walau skema
tabel berubah.

Dua hal yang paling penting untuk dibuktikan:

1. **Verifikasi tidak pernah melempar.** Satu baris `password_hash` yang rusak
   di database tidak boleh membuat seluruh endpoint login balas 500.
2. **Salt berbeda tiap hash.** Dua akun dengan password sama harus punya hash
   berbeda; kalau tidak, menebak satu berarti menebak semuanya.
"""

from __future__ import annotations

import pytest

from app.admin import security

#: Iterasi kecil khusus pengujian. 600.000 iterasi benar untuk produksi tetapi
#: membuat satu pengujian makan ~0,4 detik; parameternya sengaja bisa
#: diturunkan justru agar perilaku "iterasi tersimpan di dalam hash" teruji.
FAST_ITERATIONS = 1_000


def test_hash_lalu_verify_cocok() -> None:
    encoded = security.hash_password("rahasia-kuat-123", iterations=FAST_ITERATIONS)

    assert security.verify_password("rahasia-kuat-123", encoded)
    assert not security.verify_password("rahasia-kuat-124", encoded)


def test_format_hash_membawa_parameternya() -> None:
    """Iterasi & algoritma harus ikut di string, bukan di konstanta kode."""
    encoded = security.hash_password("apa pun", iterations=FAST_ITERATIONS)

    algorithm, iterations, salt_b64, hash_b64 = encoded.split("$")
    assert algorithm == security.ALGORITHM
    assert int(iterations) == FAST_ITERATIONS
    assert salt_b64 and hash_b64


def test_salt_berbeda_untuk_password_sama() -> None:
    """Tanpa salt acak, dua akun berpassword sama akan punya hash identik."""
    first = security.hash_password("sama-persis", iterations=FAST_ITERATIONS)
    second = security.hash_password("sama-persis", iterations=FAST_ITERATIONS)

    assert first != second
    assert security.verify_password("sama-persis", first)
    assert security.verify_password("sama-persis", second)


def test_iterasi_lama_tetap_bisa_diverifikasi() -> None:
    """Hash lama dengan iterasi lebih rendah tetap sah — itu inti portabilitas."""
    encoded = security.hash_password("lama", iterations=FAST_ITERATIONS)

    assert security.verify_password("lama", encoded)
    assert security.needs_rehash(encoded) is True


def test_hash_param_terkini_tidak_perlu_rehash() -> None:
    encoded = security.hash_password("baru", iterations=security.DEFAULT_ITERATIONS)

    assert security.needs_rehash(encoded) is False


@pytest.mark.parametrize(
    "rusak",
    [
        "",
        "bukan-hash",
        "pbkdf2_sha256$abc$c2FsdA==$aGFzaA==",  # iterasi bukan angka
        "argon2id$600000$c2FsdA==$aGFzaA==",     # algoritma lain
        "pbkdf2_sha256$600000$!!!bukan-base64$aGFzaA==",
        "pbkdf2_sha256$0$c2FsdA==$aGFzaA==",     # iterasi nol
        "pbkdf2_sha256$600000$$aGFzaA==",        # salt kosong
    ],
)
def test_verify_hash_rusak_mengembalikan_false_tanpa_melempar(rusak: str) -> None:
    """Baris rusak di database tidak boleh menjatuhkan endpoint login."""
    assert security.verify_password("apa pun", rusak) is False


def test_verify_password_kosong_selalu_false() -> None:
    encoded = security.hash_password("benar", iterations=FAST_ITERATIONS)

    assert security.verify_password("", encoded) is False


def test_password_kosong_ditolak_saat_hash() -> None:
    with pytest.raises(security.PasswordError):
        security.hash_password("")


def test_needs_rehash_menandai_hash_rusak() -> None:
    assert security.needs_rehash("bukan-hash-sama-sekali") is True


# --- Token sesi -----------------------------------------------------------


def test_token_sesi_acak_dan_panjang() -> None:
    tokens = {security.new_session_token() for _ in range(50)}

    assert len(tokens) == 50  # tidak ada tabrakan
    assert all(len(t) >= 40 for t in tokens)


def test_hash_token_stabil_dan_bukan_token_mentah() -> None:
    token = security.new_session_token()
    digest = security.hash_session_token(token)

    assert digest == security.hash_session_token(token)  # deterministik
    assert digest != token
    assert len(digest) == 64  # SHA-256 hex
    assert security.hash_session_token(token + "x") != digest


def test_dummy_hash_login_tidak_pernah_cocok() -> None:
    """Dummy verify di endpoint login tak boleh kebetulan cocok.

    Nilai ini muncul di `router_auth.login` untuk menyamakan waktu respons saat
    username tidak ditemukan. Kalau suatu saat ada password yang cocok
    dengannya, penyerang bisa masuk tanpa akun.
    """
    dummy = (
        "pbkdf2_sha256$600000$AAAAAAAAAAAAAAAAAAAAAA==$"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
    )

    for guess in ("", "a", "admin", "password", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="):
        assert security.verify_password(guess, dummy) is False
