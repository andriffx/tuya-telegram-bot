"""Test rate limiter: batas per role dan pembuangan bucket basi."""

import time

import rate_limiter as rl


def _reset():
    rl._buckets.clear()
    rl._last_prune = 0.0


def test_limit_per_role():
    _reset()
    limit = rl.LIMITS["user"]
    results = [rl.check_rate_limit(7001, "user")[0] for _ in range(limit + 1)]
    assert results[:limit] == [True] * limit
    assert results[-1] is False


def test_prune_removes_stale_buckets(monkeypatch):
    _reset()
    monkeypatch.setattr(rl, "PRUNE_INTERVAL", 0.0)

    now = time.time()
    rl._buckets[111] = [now - rl.WINDOW - 10]  # basi
    rl._buckets[222] = [now - 1]  # masih aktif

    rl.check_rate_limit(999, "public")

    assert 111 not in rl._buckets, "bucket basi harus dibuang"
    assert 222 in rl._buckets, "bucket aktif tidak boleh ikut terhapus"


def test_prune_is_throttled(monkeypatch):
    _reset()
    monkeypatch.setattr(rl, "PRUNE_INTERVAL", 3600.0)
    monkeypatch.setattr(rl, "_last_prune", time.time())

    rl._buckets[333] = [time.time() - rl.WINDOW - 10]
    rl.check_rate_limit(998, "public")

    assert 333 in rl._buckets, "prune tidak boleh jalan tiap request"
