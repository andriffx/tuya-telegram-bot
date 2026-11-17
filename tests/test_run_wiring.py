"""Regression test untuk wiring entry point run.py.

Bug yang dicegah: `housekeeping_loop` memakai `database.cleanup_old_logs`, tetapi
run.py hanya meng-import nama fungsi (`from database import init_db, log_power`)
sehingga `database` tidak pernah terdefinisi. NameError-nya tertelan
`except Exception` di dalam loop 24 jam, jadi pembersihan log tidak pernah jalan
dan tidak ada test yang gagal.
"""

import asyncio
import contextlib
import inspect

import pytest

import database
import run


def test_run_imports_database_module():
    assert hasattr(run, "database"), "run.py wajib `import database`, bukan hanya nama fungsinya"


def test_housekeeping_loop_target_is_callable():
    source = inspect.getsource(run.housekeeping_loop)
    assert "database.cleanup_old_logs" in source
    assert callable(run.database.cleanup_old_logs)
    assert callable(database.cleanup_old_logs)


def test_power_snapshot_target_is_callable():
    source = inspect.getsource(run.record_power_snapshot)
    assert "database.log_power" in source
    assert callable(run.database.log_power)


def test_run_all_initialises_database():
    source = inspect.getsource(run.run_all)
    assert "database.init_db" in source


@pytest.mark.asyncio
async def test_housekeeping_loop_actually_runs_cleanup(monkeypatch):
    """Perilaku, bukan sekadar teks: satu siklus housekeeping harus memanggil cleanup.

    Sebelum perbaikan, `database` tidak terdefinisi sehingga NameError ditelan
    `except Exception` dan cleanup tidak pernah dipanggil.
    """
    calls = []

    def fake_cleanup(*args, **kwargs):
        calls.append((args, kwargs))
        return {"power": 0, "activity": 0}

    monkeypatch.setattr(run.database, "cleanup_old_logs", fake_cleanup)

    sleeps = {"n": 0}

    async def fake_sleep(_seconds):
        sleeps["n"] += 1
        if sleeps["n"] > 1:
            raise asyncio.CancelledError
        return None

    monkeypatch.setattr(run.asyncio, "sleep", fake_sleep)

    with contextlib.suppress(asyncio.CancelledError):
        await run.housekeeping_loop(interval_hours=24)

    assert calls, "cleanup_old_logs tidak dipanggil — housekeeping mati lagi"
