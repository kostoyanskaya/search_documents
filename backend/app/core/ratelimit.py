from __future__ import annotations

import threading
import time


class RateLimiter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buckets: dict[tuple[str, str], tuple[float, float]] = {}

    def allow(
        self, key: str, bucket: str, per_minute: int
    ) -> tuple[bool, int]:
        """Returns (allowed, retry_after_seconds).
        Burst capacity == per_minute."""
        now = time.monotonic()
        rate = per_minute / 60.0
        with self._lock:
            if len(self._buckets) > 20_000:
                self._buckets = {
                    k: v for k, v in self._buckets.items() if now - v[1] < 120
                }
            tokens, last = self._buckets.get(
                (key, bucket), (float(per_minute), now)
            )
            tokens = min(float(per_minute), tokens + (now - last) * rate)
            if tokens >= 1.0:
                self._buckets[(key, bucket)] = (tokens - 1.0, now)
                return True, 0
            self._buckets[(key, bucket)] = (tokens, now)
            return False, max(1, int((1.0 - tokens) / rate) + 1)


limiter = RateLimiter()
