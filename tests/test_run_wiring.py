"""Regression test untuk wiring entry point run.py.

Bug yang dicegah: `run.py` memakai `database.cleanup_old_logs` tetapi hanya
meng-import nama fungsi (`from database import init_db, log_power`), sehingga
`database` tidak pernah terdefinisi. NameError-nya tertelan `except Exception`
di dalam loop 24 jam, jadi pembersihan log tidak pernah jalan dan tidak ada
test yang gagal. Fase 2 memindahkan loop itu ke `scheduler.py`; guard-nya
sekarang menguji job-nya, bukan loop-nya.
"""


import pytest

import tuyabot.main as run
import tuyabot.storage.sqlite_store as database


def test_run_imports_database_module():
    assert hasattr(run, "database"), "tuyabot.main.py wajib `import database`, bukan hanya nama fungsinya"


def test_housekeeping_target_is_callable():
    # main.py memakai alias modul storage, jadi cleanup yang dipanggil adalah
    # fungsi yang sama yang diimpor test (bukan salinan terpisah).
    assert run.database.cleanup_old_logs is database.cleanup_old_logs


def test_power_snapshot_target_is_callable():
    assert run.database.log_power is database.log_power


def test_run_all_initialises_database():
    assert run.database.init_db is database.init_db


@pytest.mark.asyncio
async def test_housekeeping_job_actually_runs_cleanup(monkeypatch):
    """Job housekeeping di scheduler harus benar-benar memanggil cleanup."""
    calls = []

    def fake_cleanup(*args, **kwargs):
        calls.append((args, kwargs))
        return {"power_logs_deleted": 1, "activity_logs_deleted": 2, "error_logs_deleted": 3}

    monkeypatch.setattr(run.database, "cleanup_old_logs", fake_cleanup)

    result = await run.run_housekeeping()

    assert calls, "cleanup_old_logs tidak dipanggil"
    assert result["power_logs_deleted"] == 1


def test_scheduler_registers_expected_jobs():
    scheduler = run.build_scheduler()
    names = {job.name for job in scheduler.jobs}
    assert names == {"cache-warm", "power-snapshot", "housekeeping"}
    housekeeping = next(j for j in scheduler.jobs if j.name == "housekeeping")
    # Tidak boleh jalan di awal proses; cukup sekali sehari.
    assert housekeeping.interval == run.HOUSEKEEPING_INTERVAL_HOURS * 3600
    assert housekeeping.initial_delay == housekeeping.interval
