# ADMS (Attendance Device Management System)

Another ADMS Server with fastAPI (Python 3.*) in universe. Project still development. If you want working project use adms php version, in below.

> http://go.topidesta.my.id/adms-php

Project very slow movement, so.. be patient.

## Struktur proyek

```
main.py                 # titik masuk: `uvicorn main:app --reload`
app/
  application.py        # application factory `create_app()`
  config.py             # pembacaan & validasi environment (settings)
  database.py           # connection pool MySQL
  schemas.py            # model request/response (Pydantic)
  store.py              # penyimpanan sementara di memori
  routers/
    health.py           # GET / dan GET /health
    items.py            # GET /items dan GET /items/{item_id}
tests/                  # pytest + FastAPI TestClient
docs/                   # dokumen rancangan
  PRD-ADMS-PUSH.md      # PRD implementasi protokol push ZKTeco
  PROTOCOL-SPEC.md      # referensi teknis wire protocol (untuk parser)
  SCHEMA.md             # penjelasan skema database
migrations/             # skrip migrasi SQL
  001_init_adms_push.sql
```

## Rencana: ZKTeco iClock / ADMS Push Protocol

ADMS akan menerima absensi langsung dari device ZKTeco (push), di mana
**device selalu menjadi klien** dan memanggil server kita — tidak perlu ada
port masuk ke jaringan cabang.

Baca berurutan:

1. [`docs/PRD-ADMS-PUSH.md`](docs/PRD-ADMS-PUSH.md) — tujuan, kebutuhan,
   kriteria penerimaan, tahapan
2. [`docs/PROTOCOL-SPEC.md`](docs/PROTOCOL-SPEC.md) — format wire, perintah,
   dan jebakan yang sudah terverifikasi di perangkat nyata
3. [`docs/SCHEMA.md`](docs/SCHEMA.md) — rancangan tabel + alasan tiap keputusan

Terapkan skema:

```bash
mysql -u <user> -p <database> < migrations/001_init_adms_push.sql
```

## Menjalankan

```bash
cp env.example .env      # lalu isi kredensial MySQL
pip install -r requirements.txt
uvicorn main:app --reload
```

Dokumentasi interaktif tersedia di `/docs` bila `DEBUG=true`.

## Pengujian

```bash
pytest -v
```

Pengujian tidak memerlukan MySQL — koneksi ke database dibuat malas
(lazy), sehingga test berjalan di mesin bersih.

## Konfigurasi

Semua konfigurasi dibaca dari environment variable dan divalidasi sekali
saat aplikasi start (lihat `app/config.py`). Variabel `MYSQL_HOST`,
`MYSQL_USER`, `MYSQL_PASSWORD`, dan `MYSQL_DB` bersifat wajib; bila salah
satu kosong aplikasi berhenti dengan pesan yang jelas alih-alih gagal
jauh di dalam kueri.

# Authors

- [@mdestafadilah](https://github.com/mdestafadilah)
