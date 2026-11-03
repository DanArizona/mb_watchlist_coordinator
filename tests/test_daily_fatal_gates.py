"""Offline fatal collector policy gates: independent of timing expiration.

An isolated callback fixture exercises actual DailyHotCollector.quotes against
synthetic verified native dispatch. No filesystem, credentials, HTTP or production.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest

from mb_watchlist_coordinator.daily_collector import DailyHotCollector


class FatalDailyCollectorGateTests(unittest.TestCase):
    def collector(self, *, dispatch_symbols=("ABC",), charged_calls=1,
                  requested_at=None, call_ceiling=2, max_symbols=40):
        scheduled=datetime(2026,11,3,15,57,18,tzinfo=timezone.utc)
        now=requested_at or scheduled+timedelta(milliseconds=100)
        dispatch={"scheduled_at_utc":scheduled.isoformat(),
                  "symbols":list(dispatch_symbols), "revision":2}
        state={"pending":{"dispatch":dispatch},
               "events":[{"kind":"dispatch","symbols":["ABC"]}
                         for _ in range(charged_calls)]}
        calls=[]
        class Client:
            halt_reason=None
            def quotes(self, symbols, *, fields):
                calls.append((tuple(symbols),fields))
                return SimpleNamespace(status_code=200)
        collector=object.__new__(DailyHotCollector)
        collector.poller=SimpleNamespace(provider_dispatch_state=lambda:state)
        collector.clock=lambda:now
        collector.settings=SimpleNamespace(
            max_quote_calls=call_ceiling,max_symbols=max_symbols,
            start_at_utc=(scheduled-timedelta(minutes=2)).isoformat(),
            stop_at_utc=(scheduled+timedelta(minutes=2)).isoformat(),
            daily_binding={"settings":{"policy_profile":"multi-40-v1"}})
        collector.client=Client()
        collector.refused_call=False
        collector._native_publication_state=({"journal":[]},{"authorized_symbols":["ABC"]})
        collector._check=lambda *,publication=True:None
        collector.validate_publication=lambda dispatch,*,verified_state=None:True
        return collector,calls,scheduled

    def assert_fatal(self, collector, calls, symbols, *, fields="all"):
        with self.assertRaisesRegex(ValueError,"gate refused|window expired"):
            collector.quotes(symbols,fields=fields)
        self.assertTrue(collector.refused_call, "Fatal policy gate must latch")
        self.assertEqual(calls,[], "Fatal local gate must make no provider request")

    def test_exact_roster_mismatch_is_fatal(self):
        collector,calls,_=self.collector(dispatch_symbols=("ABC",))
        self.assert_fatal(collector,calls,["DEF"])

    def test_symbol_capacity_violation_is_fatal(self):
        # More than forty symbols, even with an exactly matching dispatch.
        symbols=tuple(f"X{i:03}" for i in range(41))
        collector,calls,_=self.collector(dispatch_symbols=symbols)
        self.assert_fatal(collector,calls,list(symbols))

    def test_quote_call_budget_violation_is_fatal(self):
        collector,calls,_=self.collector(charged_calls=3,call_ceiling=2)
        self.assert_fatal(collector,calls,["ABC"])

    def test_expired_operating_window_is_fatal(self):
        slot=datetime(2026,11,3,15,57,18,tzinfo=timezone.utc)
        collector,calls,_=self.collector(requested_at=slot+timedelta(minutes=2))
        self.assert_fatal(collector,calls,["ABC"])

    def test_invalid_requested_fields_are_fatal(self):
        collector,calls,_=self.collector()
        self.assert_fatal(collector,calls,["ABC"],fields="quote")


if __name__=="__main__":
    unittest.main()
