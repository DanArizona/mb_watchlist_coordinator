"""Readiness is an active-run fact; a normal stop is truthful INCOMPLETE."""
from datetime import timedelta
import unittest

import test_daily_source as fixtures
from test_nasdaq_feed_recovery import rss


class SourceStopBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.DailySourceTests('runTest')
        self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.case,self.pump=self.fixture.case,self.fixture.pump

    def test_reconciled_source_can_truthfully_report_stop_requested_after_owner_stop(self):
        self.fixture.establish();self.case.now+=timedelta(seconds=60)
        active=self.fixture.attempt(rss(self.case.now.date(),symbol='NVDA',halt='15:57:30'))
        self.assertTrue(active['discovery_scope_reconciled'])
        self.case.now+=timedelta(milliseconds=10)
        stopped=self.pump.authority.cycle(stop_requested=lambda:True)
        self.assertEqual(stopped['status'],'INCOMPLETE')
        self.assertEqual(stopped['reasons'],['stop_requested'])
        self.assertFalse(bool(stopped.get('discovery_scope_reconciled')))
        statuses=[e for e in self.pump.authority._read()[0]if e['kind']=='status']
        self.assertTrue(statuses[-2]['discovery_scope_reconciled'])
        self.assertEqual(statuses[-1]['reasons'],['stop_requested'])

    def test_normal_stop_does_not_supply_missing_current_cutover_evidence(self):
        active=self.fixture.establish()
        self.assertFalse(active['discovery_scope_reconciled'])
        stopped=self.pump.authority.cycle(stop_requested=lambda:True)
        self.assertEqual(stopped['status'],'INCOMPLETE')
        self.assertEqual(stopped['reasons'],['stop_requested'])
        self.assertFalse(any(e.get('discovery_scope_reconciled')for e in self.pump.authority._read()[0]))


if __name__=='__main__':unittest.main()
