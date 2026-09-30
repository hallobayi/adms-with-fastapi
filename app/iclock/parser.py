"""Parser muatan (payload) yang dikirim device ke ``POST /iclock/cdata``.

Ada dua keluarga muatan dan keduanya harus ditangani:

**Absensi (ATTLOG)** — 3 varian format yang beredar di lapangan:

- *positional5*: `PIN \\t DateTime \\t Status \\t Verify \\t WorkCode`
- *positionalN*: 6+ kolom (kolom ke-3 dan seterusnya menjadi reserved)
- *keyvalue*: `PIN=.. \\t DateTime=.. \\t Status=.. \\t Verified=..`

**Biometrik/user (OPERLOG)** — juga punya dua generasi firmware:

- Legacy: `FP PIN=1\\tFID=0\\tSize=1404\\tValid=1\\tTMP=<base64>`
- PUSH SDK 2.x: `BIODATA Pin=1\\tNo=0\\tIndex=0\\tType=1\\tTmp=<base64>`

Catatan penting: **jangan** memisah field dengan `split()` biasa. Nama user
sah mengandung spasi, dan template `TMP=` adalah base64 yang harus utuh —
pemisah yang benar adalah TAB.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

#: Normalisasi CRLF/CR tunggal menjadi LF, supaya pemisahan bisa memakai
#: `str.split` biasa (C-level) alih-alih regex. `str.translate` + satu `split`
#: jauh lebih murah daripada `re.split` untuk body yang bisa ribuan baris.
_CR_TO_LF = str.maketrans("\r", "\n")

#: Timestamp gaya `YYYY-MM-DD HH:MM:SS` (bisa juga dengan `.` sebagai pemisah).
_DATETIME_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})$"
)

#: Timestamp gaya padat `YYYYMMDDHHMMSS`.
_COMPACT_DATETIME_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})$")

#: Tag yang membawa template biometrik.
TEMPLATE_TAGS = {"FP", "BIODATA"}

#: Karakter yang sah dalam base64 standar (termasuk padding `=`).
_BASE64_RE = re.compile(r"^[A-Za-z0-9+/]+={0,2}$")

#: Kode tipe biometrik ZKTeco. 1 = sidik jari.
TYPE_FINGERPRINT = 1

#: Kode status punch menurut protokol.
STATUS_LABELS = {
    0: "check_in",
    1: "check_out",
    2: "break_out",
    3: "break_in",
    4: "overtime_in",
    5: "overtime_out",
}

#: Mode verifikasi yang dikenal.
VERIFY_LABELS = {
    0: "password",
    1: "fingerprint",
    2: "card",
    3: "password",
    4: "card",
    5: "fingerprint",
    15: "face",
    25: "palm",
}


class ParseError(ValueError):
    """Muatan tidak bisa diparse menjadi baris yang berguna."""


def split_lines(payload: str) -> list[str]:
    """Pecah muatan menjadi baris tak kosong, tanpa memangkas isi field.

    Sangat sering dipanggil (3× per request) atas body yang bisa mencapai
    ribuan baris, jadi pemisahannya memakai `str.translate` + `split` bawaan
    (C-level) alih-alih regex. Perilakunya identik dengan versi regex
    sebelumnya: CRLF, CR tunggal, dan LF semuanya adalah pemisah, dan baris
    kosong (termasuk sisa CR dari CRLF) dibuang.
    """
    if not payload:
        return []
    normalized = payload.translate(_CR_TO_LF)
    return [line for line in (raw.strip() for raw in normalized.split("\n")) if line]


def parse_datetime(value: str) -> datetime | None:
    """Parse timestamp dari device.

    Menerima tiga bentuk: `YYYY-MM-DD HH:MM:SS`, pemisah `T`/spasi, dan bentuk
    padat `YYYYMMDDHHMMSS`. Mengembalikan `None` bila tidak dikenali — pemanggil
    yang memutuskan apakah barisnya dibuang atau disimpan mentah.

    **Nilai yang dikembalikan adalah waktu dinding lokal device apa adanya.**
    Konversi ke UTC dilakukan terpisah (lihat `app.iclock.timezones`), karena
    hanya di titik itu kita tahu zona device mana yang berlaku.
    """
    if not value:
        return None
    text = value.strip()

    if match := _DATETIME_RE.match(text):
        year, month, day, hour, minute, second = (int(part) for part in match.groups())
        try:
            return datetime(year, month, day, hour, minute, second)
        except ValueError:
            return None

    if match := _COMPACT_DATETIME_RE.match(text):
        year, month, day, hour, minute, second = (int(part) for part in match.groups())
        try:
            return datetime(year, month, day, hour, minute, second)
        except ValueError:
            return None

    return None


@dataclass
class AttendanceRecord:
    """Satu punch absensi yang sudah diterjemahkan dari satu baris ATTLOG."""

    pin: str
    punch_at_local: datetime
    status_code: int | None = None
    verify_mode: int | None = None
    work_code: int | None = None
    reserved: list[str] = field(default_factory=list)
    raw_line: str = ""
    format_variant: str = "positional5"

    @property
    def status_label(self) -> str | None:
        return STATUS_LABELS.get(self.status_code) if self.status_code is not None else None

    @property
    def verify_label(self) -> str | None:
        return VERIFY_LABELS.get(self.verify_mode) if self.verify_mode is not None else None


@dataclass
class UserRecord:
    """Data user seperti yang dilaporkan device."""

    pin: str
    name: str | None = None
    privilege: int | None = None
    password: str | None = None
    card_no: str | None = None
    group_id: str | None = None
    raw_line: str = ""


@dataclass
class FingerprintRecord:
    """Satu template sidik jari dari device."""

    pin: str
    finger_index: int
    template: str
    size: int | None = None
    valid: int | None = None
    duress: int | None = None
    version: str | None = None
    tag: str = "FP"
    raw_line: str = ""

    def decoded_size(self) -> int:
        """Ukuran byte template setelah base64 didekode.

        Device melaporkan `Size=` sendiri, tetapi nilai itu tidak selalu bisa
        dipercaya; ukuran hasil dekode yang dipakai untuk validasi.
        """
        return len(decode_template(self.template))


def decode_template(template: str) -> bytes:
    """Dekode template base64 menjadi byte mentah.

    **Byte hasil dekode ini disimpan apa adanya** — dilarang memotong,
    mengubah, atau "menormalkan". Format template ZKTeco tidak
    terdokumentasi resmi dan berbeda antar firmware; menebak strukturnya
    adalah cara tercepat menghasilkan data rusak yang tidak bisa dipulihkan.

    Kalau nilai yang dikirim ternyata bukan base64 yang valid, teksnya
    dikembalikan sebagai byte — lebih baik menyimpan apa adanya daripada
    membuang data.

    Pemeriksaan alfabet dilakukan **sebelum** memanggil `b64decode`, karena
    dekoder longgar bawaan Python **tidak** melempar pada input seperti
    `!bukan-base64!`: karakter tak sahnya dibuang diam-diam dan hasilnya byte
    sampah. Tanpa prapemeriksaan ini, cabang cadangan tidak pernah tercapai.
    """
    import base64
    import binascii

    text = (template or "").strip()
    if not text:
        return b""

    # Hanya bentuk yang seluruhnya base64 sah yang layak didekode.
    if _BASE64_RE.match(text):
        try:
            return base64.b64decode(text, validate=True)
        except (binascii.Error, ValueError):
            try:
                return base64.b64decode(text + "=" * (-len(text) % 4))
            except (binascii.Error, ValueError):
                pass

    return text.encode("utf-8", errors="replace")


def _to_int(value: str | None) -> int | None:
    """Konversi longgar ke int; string kosong/tak valid menjadi None."""
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def parse_keyvalue_fields(line: str) -> dict[str, str]:
    """Pecah baris `Key=Value` menjadi dict, memakai TAB sebagai pemisah.

    Nilai yang mengandung `=` (mis. base64 berpadding) tetap utuh karena
    pemisahan hanya pada `=` pertama.
    """
    fields: dict[str, str] = {}
    for chunk in line.split("\t"):
        chunk = chunk.strip()
        if not chunk or "=" not in chunk:
            continue
        key, _, value = chunk.partition("=")
        fields[key.strip().lower()] = value.strip()
    return fields


def _looks_keyvalue(line: str) -> bool:
    """Apakah baris ini berbentuk `Key=Value` dan bukan posisional."""
    head = line.split("\t", 1)[0]
    return "=" in head


def parse_attendance(payload: str) -> list[AttendanceRecord]:
    """Parse muatan ATTLOG menjadi daftar punch.

    Baris yang tidak bisa diparse **dilewati**, bukan menggagalkan seluruh
    batch: satu baris rusak tidak boleh membuang ratusan punch yang sah.
    """
    return parse_attendance_lines(split_lines(payload))


def parse_attendance_lines(lines: list[str]) -> list[AttendanceRecord]:
    """Varian `parse_attendance` untuk baris yang **sudah** dipisah.

    Dipakai jalur ingest, yang sudah memecah body sekali di depan untuk
    menghitung jumlah baris yang dikirim device — memisahkannya lagi di sini
    berarti mengulang pekerjaan yang sama untuk setiap batch.
    """
    records: list[AttendanceRecord] = []

    for line in lines:
        record = parse_attendance_line(line)
        if record is not None:
            records.append(record)

    return records


def parse_attendance_line(line: str) -> AttendanceRecord | None:
    """Parse satu baris ATTLOG. Mengembalikan `None` bila tidak berguna."""
    if not line:
        return None

    if _looks_keyvalue(line):
        return _parse_attendance_keyvalue(line)
    return _parse_attendance_positional(line)


def _parse_attendance_keyvalue(line: str) -> AttendanceRecord | None:
    fields = parse_keyvalue_fields(line)
    pin = fields.get("pin")
    stamp = parse_datetime(fields.get("datetime", "") or fields.get("time", ""))
    if not pin or stamp is None:
        return None

    return AttendanceRecord(
        pin=pin,
        punch_at_local=stamp,
        status_code=_to_int(fields.get("status")),
        verify_mode=_to_int(fields.get("verified") or fields.get("verify")),
        work_code=_to_int(fields.get("workcode")),
        raw_line=line,
        format_variant="keyvalue",
    )


def _parse_attendance_positional(line: str) -> AttendanceRecord | None:
    parts = line.split("\t")
    if len(parts) < 2:
        return None

    pin = parts[0].strip()
    stamp = parse_datetime(parts[1])
    if not pin or stamp is None:
        return None

    variant = "positional5" if len(parts) <= 5 else "positionalN"
    return AttendanceRecord(
        pin=pin,
        punch_at_local=stamp,
        status_code=_to_int(parts[2]) if len(parts) > 2 else None,
        verify_mode=_to_int(parts[3]) if len(parts) > 3 else None,
        work_code=_to_int(parts[4]) if len(parts) > 4 else None,
        reserved=[p.strip() for p in parts[5:]],
        raw_line=line,
        format_variant=variant,
    )


def looks_like_biometric_payload(line: str) -> bool:
    """Apakah baris ini membawa template biometrik atau data user."""
    head = line.split("\t", 1)[0].strip().upper()
    if head in TEMPLATE_TAGS:
        return True
    # Tag `USER` berdiri sendiri sebagai field pertama (`USER\\tPIN=..`).
    return head == "USER"


def parse_fingerprints(payload: str) -> list[FingerprintRecord]:
    """Ambil seluruh template sidik jari dari muatan OPERLOG."""
    return parse_fingerprint_lines(split_lines(payload))


def parse_fingerprint_lines(lines: list[str]) -> list[FingerprintRecord]:
    """Varian `parse_fingerprints` untuk baris yang sudah dipisah."""
    records: list[FingerprintRecord] = []

    for line in lines:
        record = parse_fingerprint_line(line)
        if record is not None:
            records.append(record)

    return records


def parse_fingerprint_line(line: str) -> FingerprintRecord | None:
    """Parse satu baris template. `None` bila baris ini bukan template."""
    tag = line.split("\t", 1)[0].strip().upper()
    if tag not in TEMPLATE_TAGS:
        return None

    fields = parse_keyvalue_fields(line)

    # `BIODATA` hanya template sidik jari bila Type=1; tipe lain (wajah,
    # telapak, vena) bukan urusan kita.
    if tag == "BIODATA":
        declared_type = _to_int(fields.get("type"))
        if declared_type is not None and declared_type != TYPE_FINGERPRINT:
            return None

    pin = fields.get("pin")
    template = fields.get("tmp") or fields.get("template")
    if not pin or not template:
        return None

    return FingerprintRecord(
        pin=pin,
        finger_index=_to_int(fields.get("fid") or fields.get("no") or fields.get("index")) or 0,
        template=template,
        size=_to_int(fields.get("size")),
        valid=_to_int(fields.get("valid")),
        duress=_to_int(fields.get("duress")),
        version=fields.get("majorver") or fields.get("version"),
        tag=tag,
        raw_line=line,
    )


def parse_users(payload: str) -> list[UserRecord]:
    """Ambil data user dari muatan OPERLOG."""
    return parse_users_lines(split_lines(payload))


def parse_users_lines(lines: list[str]) -> list[UserRecord]:
    """Varian `parse_users` untuk baris yang sudah dipisah."""
    records: list[UserRecord] = []

    for line in lines:
        if not line.split("\t", 1)[0].strip().upper().startswith("USER"):
            continue
        fields = parse_keyvalue_fields(line)
        pin = fields.get("pin")
        if not pin:
            continue
        records.append(
            UserRecord(
                pin=pin,
                name=fields.get("name"),
                privilege=_to_int(fields.get("pri") or fields.get("privilege")),
                password=fields.get("passwd") or fields.get("password"),
                card_no=fields.get("card"),
                group_id=fields.get("grp") or fields.get("group"),
                raw_line=line,
            )
        )

    return records


def parse_command_acks(body: str) -> list[tuple[int, int]]:
    """Parse konfirmasi perintah dari device menjadi `[(command_id, return), ...]`.

    Bentuk wire yang mungkin:

    - `ID=123&Return=0&CMD=DATA`
    - `ID=123\\tReturn=0\\tCMD=DATA`
    - beberapa baris sekaligus

    Mengembalikan daftar kosong bila tidak ada yang bisa diparse — pemanggil
    cukup membalas `OK` pada kasus itu.
    """
    acks: list[tuple[int, int]] = []

    for line in split_lines(body):
        fields = parse_keyvalue_fields(line.replace("&", "\t"))
        command_id = _to_int(fields.get("id"))
        if command_id is None:
            continue
        return_code = _to_int(fields.get("return"))
        acks.append((command_id, return_code if return_code is not None else -1))

    return acks
