from datetime import date

from northstar.staleness import days_since, is_stale

TODAY = date(2026, 10, 30)


def test_days_since():
    assert days_since("2026-10-30", TODAY) == 0
    assert days_since("2026-10-01", TODAY) == 29
    assert days_since("2025-10-30", TODAY) == 365
    assert days_since(None, TODAY) is None


def test_stale_only_after_the_limit():
    assert not is_stale("2026-09-25", TODAY, 35)   # exactly 35 days: not stale
    assert is_stale("2026-09-24", TODAY, 35)       # 36 days: stale


def test_no_balance_counts_as_stale():
    assert is_stale(None, TODAY, 365)


def test_slow_types_use_their_own_limit():
    assert not is_stale("2026-01-01", TODAY, 365)
    assert is_stale("2026-01-01", TODAY, 35)
