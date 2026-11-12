from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from adforge_renderer.asset_recovery_policy import (
    RETRY_CAP_SECONDS,
    RETRY_BASE_SECONDS,
    next_retry_time,
    retry_delay,
    retry_upper_bound_seconds,
)


def test_retry_upper_bound_is_bounded_exponential() -> None:
    assert retry_upper_bound_seconds(1) == RETRY_BASE_SECONDS
    assert retry_upper_bound_seconds(2) == 2 * RETRY_BASE_SECONDS
    assert retry_upper_bound_seconds(5) == 16 * RETRY_BASE_SECONDS
    assert retry_upper_bound_seconds(7) == RETRY_CAP_SECONDS
    assert retry_upper_bound_seconds(10) == RETRY_CAP_SECONDS


@pytest.mark.parametrize(
    ("sample", "expected"),
    [(0.0, 0.0), (5.0, 5.0)],
)
def test_full_jitter_includes_zero_and_upper_boundary(sample: float, expected: float) -> None:
    observed_bounds: list[tuple[float, float]] = []

    def random_source(lower: float, upper: float) -> float:
        observed_bounds.append((lower, upper))
        return sample

    assert retry_delay(1, random_source=random_source) == timedelta(seconds=expected)
    assert observed_bounds == [(0.0, RETRY_BASE_SECONDS)]


def test_next_retry_time_uses_injected_aware_clock_and_random_source() -> None:
    now = datetime(2026, 11, 12, 12, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    scheduled = next_retry_time(2, now=now, random_source=lambda _low, _high: 3.25)
    assert scheduled == datetime(2026, 11, 12, 6, 30, 3, 250000, tzinfo=timezone.utc)


@pytest.mark.parametrize("attempt", [0, -1, 11, True, 1.0])
def test_retry_policy_rejects_invalid_attempt_numbers(attempt: object) -> None:
    with pytest.raises(ValueError, match="attempt"):
        retry_upper_bound_seconds(attempt)  # type: ignore[arg-type]


@pytest.mark.parametrize("sample", [-0.1, 5.1, float("nan"), float("inf"), "1"])
def test_retry_policy_rejects_invalid_random_samples(sample: object) -> None:
    with pytest.raises(ValueError, match="random source"):
        retry_delay(1, random_source=lambda _low, _high: sample)  # type: ignore[arg-type]


def test_retry_policy_rejects_naive_clock() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        next_retry_time(1, now=datetime(2026, 11, 12))
