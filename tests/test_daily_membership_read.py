"""Daily derived membership reuse retains native persisted-value checks."""
from contextlib import closing
import sqlite3
import unittest

from mb_market_data.daily_journal import DailyQuoteObservationStore
from mb_market_data.quote_observation_store import QuoteObservationStoreError
import test_daily_session as daily


class DailyMembershipReadTests(unittest.TestCase):
    def setUp(self):
        self.case=daily.DailySessionTests('test_preview_reads_published_anchor_and_creates_no_application_state_or_client')
        self.case.setUp();self.addCleanup(self.case.doCleanups)
        self.store=DailyQuoteObservationStore(self.case.journal,session_date=self.case.at.date(),schema_version=2)
        self.before=self.store.membership_revisions_in_effective_order()

    def test_warm_reader_matches_reference_and_adopts_a_new_published_revision(self):
        self.assertEqual(self.before,self.case.store.membership_revisions_in_effective_order())
        self.assertEqual(self.store.membership_revisions_in_effective_order(),self.before)
        self.case.attach();self.case.admit()
        self.assertEqual(self.store.membership_revisions_in_effective_order(),
            self.case.store.membership_revisions_in_effective_order())
        effective=self.store.membership_revisions_in_effective_order()[-1].effective_at
        self.assertEqual(self.store.latest_membership_revision_effective_at(effective).hot_symbols,('NVDA',))

    def test_mutating_old_members_is_rejected_by_a_warm_reader(self):
        with closing(sqlite3.connect(self.case.journal)) as c,c:
            c.execute('UPDATE sampling_channel_member SET symbol="CHANGED" WHERE channel="uni" AND revision=0 AND ordinal=0')
        with self.assertRaises(QuoteObservationStoreError):self.store.membership_revisions_in_effective_order()

    def test_mutating_a_channel_header_is_rejected_by_a_warm_reader(self):
        with closing(sqlite3.connect(self.case.journal)) as c,c:
            c.execute('UPDATE sampling_channel_revision SET source="CHANGED" WHERE channel="uni" AND revision=0')
        with self.assertRaises(QuoteObservationStoreError):self.store.membership_revisions_in_effective_order()

    def test_mutating_a_hierarchy_header_is_rejected_by_a_warm_reader(self):
        with closing(sqlite3.connect(self.case.journal)) as c,c:
            c.execute('UPDATE sampling_membership_revision SET content_sha256=? WHERE revision=0',('0'*64,))
        with self.assertRaises(QuoteObservationStoreError):self.store.membership_revisions_in_effective_order()

    def test_deleted_channel_is_rejected_by_a_warm_latest_reader(self):
        with closing(sqlite3.connect(self.case.journal)) as c,c:
            c.execute('DELETE FROM sampling_channel_revision WHERE channel="hot" AND revision=1')
        with self.assertRaises(QuoteObservationStoreError):self.store.latest_membership_revision_effective_at(self.case.now)


if __name__=='__main__':unittest.main()
