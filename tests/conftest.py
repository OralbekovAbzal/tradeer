"""Test fixtures: isolated in-memory-ish SQLite per test, no network."""
from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Point the app at a fresh temp database and reset cached singletons."""
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("TRADEER_DB_PATH", str(db_file))
    monkeypatch.setenv("TRADEER_MAX_POSITION_PCT", "0.25")
    monkeypatch.setenv("TRADEER_MAX_SECTOR_PCT", "0.40")
    monkeypatch.setenv("TRADEER_MAX_DRAWDOWN_PCT", "0.20")

    # Reset the cached settings and the lazily-built engine/session factory.
    import config.settings as settings_mod
    import storage.db as db_mod

    settings_mod.get_settings.cache_clear()
    db_mod._engine = None
    db_mod._SessionFactory = None

    importlib.reload  # keep import; modules read singletons lazily
    db_mod.init_db()
    yield db_file

    db_mod._engine = None
    db_mod._SessionFactory = None
    settings_mod.get_settings.cache_clear()
