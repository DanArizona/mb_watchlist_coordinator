"""Daily paced Nasdaq transport using the existing durable HTTP receipts.

No live CLI: a trusted authenticated owner supplies explicit network permission.
The original ten-attempt/720-second feed limits and worker remain unchanged.
"""
from dataclasses import dataclass
import math
from pathlib import Path

from .nasdaq_feed_recovery import FeedRecoveryTransport, BoundedFeedClient
from .nasdaq_recovery import regular_window


@dataclass(frozen=True)
class DailyFeedLimits:
    interval_seconds: int = 60
    max_attempts: int = 390
    budget_seconds: int = 23400
    hard_timeout_seconds: float = 10
    consecutive_failures: int = 3

    def __post_init__(self):
        if (type(self.interval_seconds) is not int or self.interval_seconds < 60
                or type(self.max_attempts) is not int or not 1 <= self.max_attempts <= 390
                or type(self.budget_seconds) is not int or not 1 <= self.budget_seconds <= 23400
                or type(self.consecutive_failures) is not int or not 1 <= self.consecutive_failures <= 3
                or type(self.hard_timeout_seconds) not in (int,float)
                or not math.isfinite(self.hard_timeout_seconds) or not .1 <= self.hard_timeout_seconds <= 10):
            raise ValueError('Explicit bounded daily feed limits required')


def collection_feed_limits(collector):
    """Derive durable source ceilings from the immutable collection window.

    Retain the original full-day defaults. A short invocation allows one spare
    attempt so the final fresh CURRENT can establish readiness before the
    attempt ceiling is exhausted. Pacing and HTTP timeout are unchanged.
    """
    from .sampling_requests import timestamp
    raw = collector.payload()
    seconds = math.ceil((timestamp(raw['stop_at_utc'])-timestamp(raw['start_at_utc'])).total_seconds())
    return DailyFeedLimits(max_attempts=min(390, math.ceil(seconds/60)+1),
        budget_seconds=min(23400, seconds))


class DailyFeedTransport(FeedRecoveryTransport):
    def __init__(self, *args, limits=None, **kwargs):
        if limits is not None and type(limits) is not DailyFeedLimits:
            raise ValueError('Daily feed requires its distinct explicit limits type')
        super().__init__(*args, limits=limits or DailyFeedLimits(), **kwargs)
        self.start, self.stop = regular_window(self.session_date)

    def _window(self):
        if (self.start,self.stop) != regular_window(self.session_date):
            raise ValueError('Daily feed regular-session boundary changed')

    def snapshot(self):
        self._window()
        return super().snapshot()

    def reserve(self, query=None, *, synthetic=False):
        self._window()
        if not self.start <= self.clock() < self.stop: return None
        return super().reserve(query, synthetic=synthetic)

    def finish(self, reservation, *, unknown=None):
        self._window()
        # Preserve incomplete/unknown responses that cross close; never label
        # a late HTTP body as a usable normal capture.
        if self.clock() >= self.stop: unknown = unknown or 'hard_deadline'
        return super().finish(reservation, unknown=unknown)


class DailyFeedClient(BoundedFeedClient):
    def __init__(self,transport,**kwargs):
        if type(transport) is not DailyFeedTransport:
            raise ValueError('Daily feed client requires its bound daily transport')
        super().__init__(transport,**kwargs)

    def worker_entry(self):
        return Path(__file__).with_name('daily_feed_worker.py')

    def step(self, query=None, *, synthetic=None, stop_requested=lambda:False):
        return super().step(query, synthetic=synthetic,
            stop_requested=lambda: stop_requested() or self.transport.clock() >= self.transport.stop)
