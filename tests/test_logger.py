"""Uji konfigurasi logging terpusat (`app/logger.py`).

Sebelum modul itu ada, 18 modul memanggil `logging.getLogger(__name__)` tanpa
ada satu pun yang memasang handler — akibatnya seluruh `logger.info(...)` di
jalur ingest dan dashboard tidak pernah terlihat. Berkas ini menjaga agar
kondisi itu tidak kembali.
"""

from __future__ import annotations

import logging

import pytest

from app.logger import DEFAULT_LEVEL, configure_logging, setup_logger

_OUR_HANDLERS = "adms"


def _our_handlers() -> list[logging.Handler]:
    return [h for h in logging.getLogger().handlers if h.get_name() == _OUR_HANDLERS]


@pytest.fixture(autouse=True)
def _restore_root_logger():
    """Kembalikan root logger ke keadaan semula setelah tiap uji."""
    root = logging.getLogger()
    before_handlers = list(root.handlers)
    before_level = root.level
    yield
    for handler in list(root.handlers):
        if handler not in before_handlers:
            root.removeHandler(handler)
    root.setLevel(before_level)


def test_configure_logging_memasang_tepat_satu_handler() -> None:
    configure_logging("INFO")
    assert len(_our_handlers()) == 1


def test_configure_logging_idempoten() -> None:
    """Dipanggil berkali-kali (mis. tiap `create_app()` di test) tidak boleh
    menumpuk handler — tumpukan handler membuat satu baris log tercetak berkali-kali."""
    configure_logging("INFO")
    configure_logging("INFO")
    configure_logging("DEBUG")
    assert len(_our_handlers()) == 1


def test_log_info_dari_modul_sampai_ke_handler(capsys) -> None:
    """Inti perbaikannya: log INFO modul biasa benar-benar keluar."""
    configure_logging("INFO")
    logging.getLogger("app.iclock.ingest").info("halo-dari-ingest")

    assert "halo-dari-ingest" in capsys.readouterr().out


def test_level_menyaring_log_yang_lebih_rendah(capsys) -> None:
    configure_logging("WARNING")
    logging.getLogger("app.sesuatu").info("tidak-boleh-muncul")

    assert "tidak-boleh-muncul" not in capsys.readouterr().out


def test_debug_bisa_dinyalakan(capsys) -> None:
    """DEBUG inilah yang dipakai saat menelusuri device yang diam."""
    configure_logging("debug")
    logging.getLogger("app.sesuatu").debug("detail-debug")

    assert "detail-debug" in capsys.readouterr().out


def test_nama_level_tak_dikenal_jatuh_ke_default() -> None:
    """Nilai LOG_LEVEL yang salah tidak boleh membuat aplikasi gagal start."""
    configure_logging("BUKAN-LEVEL")
    assert logging.getLogger().level == logging.getLevelName(DEFAULT_LEVEL)


def test_tanpa_warna_bila_bukan_terminal(capsys) -> None:
    """Log yang dialihkan ke berkas harus bersih dari escape ANSI."""
    configure_logging("INFO")
    logging.getLogger("app.sesuatu").info("pesan-biasa")

    assert "\033[" not in capsys.readouterr().out


def test_setup_logger_mengembalikan_logger_bernama() -> None:
    logger = setup_logger("app.uji")
    assert isinstance(logger, logging.Logger)
    assert logger.name == "app.uji"
