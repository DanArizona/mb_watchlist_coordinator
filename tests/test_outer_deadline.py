import subprocess
import unittest
from mb_watchlist_coordinator.outer_deadline import OuterBounds, stop_owned


class Child:
    def __init__(self, code=None, timeout=False):
        self.returncode=code;self.timeout=timeout;self.calls=[]
    def poll(self):return self.returncode
    def terminate(self):self.calls.append('terminate')
    def wait(self, timeout):
        self.calls.append(timeout)
        if self.timeout:raise subprocess.TimeoutExpired('owned-fixture',timeout)
        self.returncode=-15


class OuterDeadlineTests(unittest.TestCase):
    def test_fixed_cleanup_and_reporting_endpoints(self):
        b=OuterBounds(100);self.assertEqual(b.cleanup_end,110);self.assertEqual(b.report_end,170)
    def test_invalid_bounds(self):
        for args in [(float('nan'),),(100,11),(100,10,61),(True,)]:
            with self.assertRaises(ValueError):OuterBounds(*args)
    def test_already_exited_is_not_signalled(self):
        c=Child(0);self.assertEqual(stop_owned(c,OuterBounds(100),monotonic=lambda:101)['status'],'EXIT_OBSERVED');self.assertEqual(c.calls,[])
    def test_cleanup_does_not_renew_original_deadline(self):
        c=Child();self.assertEqual(stop_owned(c,OuterBounds(100),monotonic=lambda:108)['status'],'EXIT_OBSERVED');self.assertEqual(c.calls,['terminate',2])
    def test_expired_cleanup_does_not_start_another_wait(self):
        c=Child();self.assertEqual(stop_owned(c,OuterBounds(100),monotonic=lambda:110)['status'],'CLEANUP_INCOMPLETE');self.assertEqual(c.calls,[])
    def test_timeout_never_claims_exit(self):
        c=Child(timeout=True);self.assertEqual(stop_owned(c,OuterBounds(100),monotonic=lambda:101)['status'],'CLEANUP_INCOMPLETE');self.assertIsNone(c.returncode)
    def test_early_stop_has_only_ten_seconds_and_cannot_extend_original_end(self):
        b=OuterBounds(100).stopped_at(20)
        self.assertEqual(b.cleanup_end,30);self.assertEqual(b.report_end,90)
        self.assertEqual(b.stopped_at(50).cleanup_end,30)
