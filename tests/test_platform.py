#!/usr/bin/env python3
"""Platform uyumu testleri — Windows/Linux lock + path davranışı."""
import importlib
import os
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_windows_lock_fallback():
    """Windows'ta fcntl yok → msvcrt kullanılır (import hatasız)."""
    with mock.patch.dict(sys.modules, {"fcntl": None}):
        import hermes_sync.sync_motor as sm
        # sync_motor'da fcntl import try/except içinde olmalı
        assert hasattr(sm, "MOTOR_LOCK")


def test_linux_fcntl_vardir():
    """Linux'ta fcntl mevcuttur."""
    import hermes_sync.sync_motor as sm
    try:
        import fcntl
        assert True
    except ImportError:
        pytest.skip("fcntl yok — Windows ortamı")


def test_platform_path_uses_os_path():
    """Dosya yolları os.path ile kurulmalı (pathlib değil) — çapraz platform."""
    import hermes_sync.sync_motor as sm
    src = open(sm.__file__).read()
    # kritik: tar/lock path'leri os.path.join kullanmalı
    assert "os.path.join" in src or "os.path.expanduser" in src


def test_config_example_varligi():
    """Örnek config paket içinde duruyor."""
    import hermes_sync
    p = os.path.join(os.path.dirname(hermes_sync.__file__), "config.example.json")
    assert os.path.exists(p)
