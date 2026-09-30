"""Hashing password & token sesi untuk dashboard admin.

Kenapa PBKDF2 dari stdlib dan bukan argon2/bcrypt:

- `hashlib.pbkdf2_hmac` adalah implementasi **C dari stdlib** — tidak menambah
  dependensi yang harus dirawat atau di-pin, dan tidak bisa "lupa terpasang"
  di server produksi. `argon2-cffi` secara teknis lebih kuat, tetapi kekuatan
  tambahannya tidak sepadan dengan risiko dependensi yang gagal build.
- PBKDF2-HMAC-SHA256 adalah algoritma yang **direkomendasikan OWASP** (minimal
  600.000 iterasi), jadi ini bukan kompromi keamanan — hanya pilihan yang lebih
  sederhana untuk dioperasikan.

Yang penting dan tidak boleh dilanggar:

1. **Parameter disimpan di dalam string hash**, bukan di konstanta kode. Format
   `pbkdf2_sha256$<iterasi>$<salt_b64>$<hash_b64>`, sehingga jumlah iterasi bisa
   dinaikkan kelak dan hash lama tetap bisa diverifikasi.
2. **Perbandingan memakai `hmac.compare_digest`** (constant-time). Perbandingan
   `==` biasa membocorkan berapa banyak karakter awal yang cocok lewat waktu
   respons, dan itu cukup untuk menebak hash byte demi byte.
3. **Token sesi disimpan sebagai hash SHA-256**, bukan token mentah. Bila isi
   tabel bocor lewat backup atau dump, token tidak langsung bisa dipakai.
   SHA-256 cukup di sini (bukan PBKDF2) karena token dibuat acak 256-bit —
   tidak ada yang bisa ditebak, jadi memperlambat brute force tidak berguna.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

#: Algoritma KDF yang dipakai. Ikut tertulis di string hash supaya verifikasi
#: tidak bergantung pada konstanta kode saat formatnya berubah.
ALGORITHM = "pbkdf2_sha256"

#: Iterasi minimum sesuai rekomendasi OWASP untuk PBKDF2-HMAC-SHA256 (2023).
#: Dipakai untuk hash baru; hash lama dengan angka lebih rendah tetap diterima.
DEFAULT_ITERATIONS = 600_000

#: Panjang salt (byte) dan panjang kunci turunan (byte).
_SALT_BYTES = 16
_KEY_BYTES = 32

#: Panjang token sesi yang dikirim ke browser (byte acak -> 43 karakter url-safe).
SESSION_TOKEN_BYTES = 32


class PasswordError(ValueError):
    """Password tidak memenuhi syarat minimal."""


def hash_password(
    password: str, *, iterations: int = DEFAULT_ITERATIONS
) -> str:
    """Hash password menjadi string portabel `pbkdf2_sha256$iter$salt$hash`."""
    if not password:
        raise PasswordError("Password tidak boleh kosong.")

    salt = secrets.token_bytes(_SALT_BYTES)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, _KEY_BYTES)

    return "$".join(
        (
            ALGORITHM,
            str(iterations),
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(derived).decode("ascii"),
        )
    )


def verify_password(password: str, encoded: str) -> bool:
    """Verifikasi password terhadap string hash.

    Mengembalikan `False` (bukan melempar) untuk hash yang rusak/tidak dikenal:
    baris yang cacat di database tidak boleh menggagalkan seluruh endpoint login
    dengan 500 — pemanggil hanya perlu tahu "tidak cocok".
    """
    if not password or not encoded:
        return False

    try:
        algorithm, iterations_text, salt_b64, hash_b64 = encoded.split("$")
    except ValueError:
        return False

    if algorithm != ALGORITHM:
        return False

    try:
        iterations = int(iterations_text)
        salt = base64.b64decode(salt_b64, validate=True)
        expected = base64.b64decode(hash_b64, validate=True)
    except (ValueError, TypeError):
        return False

    if iterations <= 0 or not salt or not expected:
        return False

    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, len(expected))

    # Constant-time: `==` akan membocorkan panjang kecocokan lewat waktu.
    return hmac.compare_digest(derived, expected)


def needs_rehash(encoded: str) -> bool:
    """Apakah hash ini sebaiknya dihitung ulang dengan parameter terkini?

    Dipanggil setelah login berhasil. Ini yang membuat menaikkan
    `DEFAULT_ITERATIONS` di kemudian hari benar-benar berlaku untuk akun lama
    tanpa memaksa semua orang mengganti password.
    """
    try:
        algorithm, iterations_text, _, _ = encoded.split("$")
    except ValueError:
        return True
    if algorithm != ALGORITHM:
        return True
    try:
        return int(iterations_text) < DEFAULT_ITERATIONS
    except ValueError:
        return True


# --- Sesi ----------------------------------------------------------------


def new_session_token() -> str:
    """Token sesi acak yang aman secara kriptografis."""
    return secrets.token_urlsafe(SESSION_TOKEN_BYTES)


def hash_session_token(token: str) -> str:
    """Hash token sesi untuk disimpan di database.

    Memakai SHA-256 tanpa salt dengan sengaja: token dibuat acak 256-bit,
    jadi tidak ada kamus yang bisa dipakai menyerangnya, dan kita butuh
    pencarian **berdasarkan hash** (indeks unik) saat memvalidasi cookie —
    salt per-baris akan memaksa pemindaian seluruh tabel.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
