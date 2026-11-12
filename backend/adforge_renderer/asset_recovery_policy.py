"""Bounded development retry policy for local upload recovery."""

from __future__ import annotations

import math
import random
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from .database.models import ASSET_RECOVERY_MAX_ATTEMPTS


RETRY_BASE_SECONDS = 5.0
RETRY_CAP_SECONDS = 5 * 60.0
RandomSource = Callable[[float, float], float]


def retry_upper_bound_seconds(attempt: int) -> float:
    """Return the bounded exponential upper limit for a 1-based attempt."""
    if type(attempt) is not int or not 1 <= attempt <= ASSET_RECOVERY_MAX_ATTEMPTS:
        raise ValueError("Recovery attempt must be between one and the configured maximum.")
    exponent = attempt - 1
    # Avoid constructing an enormous integer/float for adversarial input; the
    # attempt bound is enforced first, and cap before exponentiation can grow.
    return min(RETRY_BASE_SECONDS * (2 ** exponent), RETRY_CAP_SECONDS)


def retry_delay(
    attempt: int,
    *,
    random_source: RandomSource | None = None,
) -> timedelta:
    """Calculate full-jitter delay using an injectable uniform source."""
    upper = retry_upper_bound_seconds(attempt)
    source = random_source or random.uniform
    delay = source(0.0, upper)
    if isinstance(delay, bool) or not isinstance(delay, (int, float)):
        raise ValueError("Retry random source returned an invalid value.")
    if not math.isfinite(delay) or delay < 0 or delay > upper:
        raise ValueError("Retry random source returned a value outside the allowed range.")
    return timedelta(seconds=float(delay))


def next_retry_time(
    attempt: int,
    *,
    now: datetime,
    random_source: RandomSource | None = None,
) -> datetime:
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError("Retry time requires a timezone-aware timestamp.")
    return now.astimezone(timezone.utc) + retry_delay(attempt, random_source=random_source)
