"""Independent elapsed deadlines for an explicitly supplied owned process.

No process discovery, runtime restart, credential handling or live launcher.
"""
from dataclasses import dataclass
import math
import time


@dataclass(frozen=True)
class OuterBounds:
    active_end: float
    cleanup_seconds: float = 10.0
    report_seconds: float = 60.0

    def __post_init__(self):
        if (any(type(x) not in (int, float) or not math.isfinite(x)
                for x in (self.active_end, self.cleanup_seconds, self.report_seconds))
                or not 0 < self.cleanup_seconds <= 10
                or not 0 < self.report_seconds <= 60):
            raise ValueError('Invalid outer bounds')

    @property
    def cleanup_end(self):
        return self.active_end + self.cleanup_seconds

    @property
    def report_end(self):
        return self.cleanup_end + self.report_seconds

    def stopped_at(self, observed):
        """Freeze an earlier stop once; never grant the unused active window."""
        if type(observed) not in (int, float) or not math.isfinite(observed):
            raise ValueError('Invalid stop observation')
        return OuterBounds(min(self.active_end, observed), self.cleanup_seconds, self.report_seconds)


def stop_owned(child, bounds, *, monotonic=time.monotonic):
    """Terminate only the supplied Popen handle; never wait beyond cleanup end.

    The caller must establish ownership before passing the handle. A timeout
    is explicit incomplete cleanup, never evidence that a process exited.
    """
    if child.poll() is not None:
        return {'status': 'EXIT_OBSERVED', 'returncode': child.returncode}
    remaining = bounds.cleanup_end - monotonic()
    if remaining <= 0:
        return {'status': 'CLEANUP_INCOMPLETE', 'returncode': None}
    child.terminate()
    import subprocess
    try:
        child.wait(timeout=max(0, bounds.cleanup_end-monotonic()))
    except subprocess.TimeoutExpired:
        return {'status': 'CLEANUP_INCOMPLETE', 'returncode': None}
    return {'status': 'EXIT_OBSERVED', 'returncode': child.returncode}
