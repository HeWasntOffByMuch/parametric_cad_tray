"""Per-client limits for the endpoints that cost CPU.

The primary guard against resource exhaustion is still parameter validation -
nothing expensive starts unless the geometry is buildable.  This is the second
layer: it stops a client from queueing a hundred *valid* builds.

Cheap endpoints (schema, presets, version, validate, health, artifacts) are not
limited.  Validation is ~2 ms and the UI calls it on every edit; rate-limiting it
would break the product to protect nothing.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass

from .settings import SETTINGS


@dataclass(frozen=True)
class LimitDecision:
    allowed: bool
    reason: str = ""
    retry_after_s: float = 0.0


class RateLimiter:
    """Sliding window per client, plus a cap on jobs in flight."""

    def __init__(
        self,
        requests: int | None = None,
        window_s: float | None = None,
        max_concurrent: int | None = None,
    ):
        self.requests = SETTINGS.rate_limit_requests if requests is None else requests
        self.window_s = SETTINGS.rate_limit_window_s if window_s is None else window_s
        self.max_concurrent = (
            SETTINGS.max_concurrent_jobs_per_client if max_concurrent is None else max_concurrent
        )
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._inflight: dict[str, int] = defaultdict(int)
        self._lock = threading.Lock()

    def check_rate(self, client: str) -> LimitDecision:
        """Sliding-window test, recorded on success.  Applied to every build
        request, including ones that turn out to be cache hits: the cost being
        limited here is the request itself."""
        now = time.monotonic()
        with self._lock:
            hits = self._hits[client]
            while hits and now - hits[0] > self.window_s:
                hits.popleft()
            if len(hits) >= self.requests:
                return LimitDecision(
                    False,
                    f"more than {self.requests} build requests in {self.window_s:.0f}s",
                    round(self.window_s - (now - hits[0]), 2),
                )
            hits.append(now)
            return LimitDecision(True)

    def try_acquire(self, client: str) -> LimitDecision:
        """Take a concurrency slot, if one is free.

        Only a request that actually starts a build calls this.  A cache hit
        costs nothing, and a request that attaches to an identical build already
        running occupies no extra worker - refusing either would punish a client
        for asking for something cheap.
        """
        with self._lock:
            if self._inflight[client] >= self.max_concurrent:
                return LimitDecision(False, "too many builds already running for this client", 1.0)
            self._inflight[client] += 1
            return LimitDecision(True)

    def release(self, client: str) -> None:
        with self._lock:
            if self._inflight[client] > 0:
                self._inflight[client] -= 1

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "clients": len(self._hits),
                "in_flight": sum(self._inflight.values()),
                "requests_per_window": self.requests,
                "window_s": self.window_s,
                "max_concurrent_per_client": self.max_concurrent,
            }
