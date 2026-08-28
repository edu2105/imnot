from __future__ import annotations

import logging
import math
from dataclasses import dataclass

_http_logger = logging.getLogger("imnot.http")


@dataclass
class TokenBucket:
    tokens: float
    last_refill: float


def _refill(bucket: TokenBucket, capacity: int, refill_per_second: float, now: float) -> None:
    elapsed = now - bucket.last_refill
    if elapsed > 0:
        bucket.tokens = min(capacity, bucket.tokens + elapsed * refill_per_second)
    bucket.last_refill = now


class RateLimiter:
    def __init__(self) -> None:
        self._buckets: dict[tuple, TokenBucket] = {}

    def check(self, key: tuple, capacity: int, refill_per_second: float, now: float) -> tuple[bool, int]:
        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = TokenBucket(tokens=capacity, last_refill=now)
            self._buckets[key] = bucket
        else:
            _refill(bucket, capacity, refill_per_second, now)

        if bucket.tokens >= 1:
            bucket.tokens -= 1
            allowed = True
            retry_after = 0
        else:
            allowed = False
            retry_after = max(1, math.ceil((1 - bucket.tokens) / refill_per_second))

        _http_logger.debug(
            "Rate limit check key=%s capacity=%s tokens_remaining=%s allowed=%s retry_after=%s",
            key,
            capacity,
            bucket.tokens,
            allowed,
            retry_after,
        )

        return allowed, retry_after
