"""Endpoint `/iclock/*` yang dipanggil device ZKTeco.

**Device selalu menjadi klien.** Server tidak pernah membuka koneksi ke device —
tidak ada port masuk ke jaringan cabang, dan semua perintah dikirim lewat
balasan `getrequest` yang ditanyakan device sendiri secara berkala.

Empat endpoint yang wajib ada:

======================  ==============================================
`GET  /iclock/cdata`    handshake (device minta konfigurasi)
`POST /iclock/cdata`    unggahan data (ATTLOG / OPERLOG / USERINFO)
`GET  /iclock/getrequest`  poll perintah
`POST /iclock/devicecmd`   konfirmasi perintah
======================  ==============================================

Catatan yang menentukan berhasil/gagal:

- Balasan **`text/plain`**, bukan JSON. Firmware ini tidak memparse JSON.
- Balasan `POST /iclock/cdata` berisi **jumlah baris yang DIKIRIM** device, bukan
  jumlah yang disimpan. Device memakai angka itu sebagai penanda posisi
  unggahan; memberi angka lebih kecil membuatnya mengirim ulang selamanya.
- Kegagalan internal **tetap dibalas `OK`** selama body-nya sudah diarsipkan.
  Device tidak punya konsep "coba lagi nanti karena server sedang sibuk" — ia
  hanya akan mengulang, dan itu justru memperburuk keadaan.
- **Penyimpanan berjalan di thread pool.** `mysql-connector` bersifat
  blocking, sedangkan endpoint di sini `async`. Menjalankan I/O database
  langsung di event loop akan memblokir *seluruh* device lain selama satu
  batch ditulis; `anyio.to_thread.run_sync` memindahkannya ke worker thread
  sehingga banyak device bisa ditangani bersamaan.
"""

from __future__ import annotations

import logging
import time
from functools import partial

import anyio.to_thread
from fastapi import APIRouter, Request, Response
from fastapi.responses import PlainTextResponse

from app.iclock import ingest, protocol

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/iclock", tags=["iclock"])

#: Semua balasan ke device adalah teks polos. Header ini juga mencegah
#: middleware menambahkan charset yang membingungkan firmware lama.
PLAIN = {"Content-Type": "text/plain"}


async def _run_blocking(func, /, **kwargs):
    """Jalankan fungsi yang memakai I/O database blocking di worker thread.

    Endpoint `/iclock/*` didefinisikan `async` (FastAPI hanya memberi thread
    pool otomatis pada endpoint `def`), tetapi `mysql-connector` tidak punya
    API async. Menjalankannya langsung akan menahan event loop selama kueri
    berlangsung — dan karena device melakukan polling berkala, satu batch
    besar milik satu device bisa menunda semua device lain.

    `anyio.to_thread.run_sync` (yang dipakai Starlette sendiri di balik layar)
    memindahkan pekerjaan itu ke worker thread, sehingga event loop tetap
    melayani request lain sambil menunggu MySQL.
    """
    return await anyio.to_thread.run_sync(partial(func, **kwargs))


def _client_ip(request: Request) -> str | None:
    """IP device. Menghormati `X-Forwarded-For` karena server biasanya di balik
    reverse proxy (nginx)."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def _query_params(request: Request) -> dict[str, str]:
    return {str(k): str(v) for k, v in request.query_params.items()}


async def _read_body(request: Request) -> str:
    """Baca body mentah sebagai teks.

    Device mengirim teks, bukan JSON, dan encoding-nya tidak selalu dinyatakan
    dengan benar — jadi decode longgar supaya satu byte aneh tidak membuang
    seluruh batch.
    """
    raw = await request.body()
    if not raw:
        return ""
    return raw.decode("utf-8", errors="replace")


@router.get("/cdata", response_class=PlainTextResponse)
async def handshake(request: Request) -> Response:
    """Handshake: device minta konfigurasinya.

    Dipanggil saat pertama kali connect dan setiap kali device reboot. Ini
    juga momen di mana device baru muncul di tabel `device` dengan
    `status='pending'`.

    **Device yang belum disetujui tetap dilayani.** Kalau tidak, ia berhenti
    mencoba, dan kita kehilangan kesempatan mengetahuinya ada.
    """
    serial_number = request.query_params.get("SN", "").strip() or None
    params = _query_params(request)
    body = await _read_body(request)

    if not serial_number:
        # Tanpa SN kita tidak bisa melakukan apa pun yang berarti. Ini bukan
        # serangan; firmware tertentu memang memanggil tanpa SN kadang.
        logger.warning("Handshake tanpa SN dari %s", _client_ip(request))
        return PlainTextResponse("ERROR: SN required", status_code=200, headers=PLAIN)

    result = await _run_blocking(
        ingest.handle_handshake,
        serial_number=serial_number,
        query_params=params,
        body=body,
        source_ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    response = protocol.handshake_response(serial_number, op_stamp=int(time.time()))

    return PlainTextResponse(response, status_code=200, headers=PLAIN)


@router.post("/cdata", response_class=PlainTextResponse)
async def receive_records(request: Request) -> Response:
    """Terima unggahan data dari device: ATTLOG, OPERLOG, atau USERINFO.

    Selalu membalas `OK: <jumlah baris yang dikirim>`. Bahkan bila penyimpanan
    gagal, body mentah tetap sudah diarsipkan sehingga data tidak hilang dan
    bisa diproses ulang setelah masalahnya diperbaiki.
    """
    serial_number = request.query_params.get("SN", "").strip() or None
    params = _query_params(request)
    body = await _read_body(request)

    if not serial_number:
        logger.warning("POST cdata tanpa SN dari %s", _client_ip(request))
        return PlainTextResponse("OK: 0", status_code=200, headers=PLAIN)

    sent = await _run_blocking(
        ingest.handle_records,
        serial_number=serial_number,
        query_params=params,
        body=body,
        source_ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    # Angka yang dibalas adalah jumlah yang DIKIRIM, bukan yang disimpan.
    return PlainTextResponse(f"OK: {sent}", status_code=200, headers=PLAIN)


@router.get("/getrequest", response_class=PlainTextResponse)
async def get_request(request: Request) -> Response:
    """Poll perintah: device menanyakan apakah ada yang harus dikerjakan.

    Ini **satu-satunya** jalur perintah ke device. Bila tidak ada antrean,
    balasannya `OK` — bukan string kosong, karena device tertentu memperlakukan
    balasan kosong sebagai kegagalan dan langsung mencoba lagi (efeknya:
    lonjakan request tanpa henti).
    """
    serial_number = request.query_params.get("SN", "").strip() or None

    if not serial_number:
        return PlainTextResponse("OK", status_code=200, headers=PLAIN)

    commands = await _run_blocking(ingest.take_commands, serial_number=serial_number)
    if not commands:
        return PlainTextResponse("OK", status_code=200, headers=PLAIN)

    # Perintah dipisah CRLF, tanpa CRLF di ujung terakhir.
    return PlainTextResponse("\r\n".join(commands), status_code=200, headers=PLAIN)


@router.post("/devicecmd", response_class=PlainTextResponse)
async def device_command(request: Request) -> Response:
    """Konfirmasi perintah: device melaporkan hasil menjalankan perintah.

    Bentuk wire: `ID=123&Return=0&CMD=DATA`. `Return=0` berarti sukses.
    """
    serial_number = request.query_params.get("SN", "").strip() or None
    body = await _read_body(request)

    if not serial_number:
        return PlainTextResponse("OK", status_code=200, headers=PLAIN)

    # Body ack bisa datang sebagai body atau sebagai query/form param,
    # tergantung firmware.
    if not body.strip() and request.query_params:
        body = "&".join(f"{k}={v}" for k, v in request.query_params.items())

    await _run_blocking(
        ingest.handle_command_acks, serial_number=serial_number, body=body
    )

    return PlainTextResponse("OK", status_code=200, headers=PLAIN)


@router.get("/ping", response_class=PlainTextResponse)
async def ping(request: Request) -> Response:
    """Balas cepat untuk device yang memeriksa ketersediaan server.

    Sengaja tidak menyentuh database: kalau database bermasalah, handshake dan
    unggahan tetap harus dilayani, dan ping sebaiknya tidak menambah beban.
    """
    return PlainTextResponse("OK", status_code=200, headers=PLAIN)


@router.get("/registry", response_class=PlainTextResponse)
async def registry(request: Request) -> Response:
    """Laporkan balik registry fitur. Balasan `OK` sudah cukup bagi device."""
    return PlainTextResponse("OK", status_code=200, headers=PLAIN)


@router.get("/rtdata", response_class=PlainTextResponse)
async def realtime_data(request: Request) -> Response:
    """Unggahan realtime. Device hanya perlu `last_seen` diperbarui."""
    serial_number = request.query_params.get("SN", "").strip() or None
    if serial_number:
        await _run_blocking(ingest.touch, serial_number=serial_number)
    return PlainTextResponse("ok", status_code=200, headers=PLAIN)
