from pathlib import Path
import json
import unittest

import test_daily_session as fixture
from mb_watchlist_coordinator.daily_operating_review import build_operating_review
from mb_watchlist_coordinator.sampling_requests import digest,plain


class DailyOperatingReviewTests(unittest.TestCase):
    def setUp(self):
        self.case=fixture.DailySessionTests('test_preview_reads_published_anchor_and_creates_no_application_state_or_client')
        self.case.setUp();self.addCleanup(self.case.doCleanups)

    def review(self):
        c=self.case
        return build_operating_review(c.r0,c.r1,journal=c.journal,catalog=c.root/'catalog',
            state_root=c.settings.state_root,ecfg=c.root/'unused.ecfg',clock=lambda:c.now)

    def test_public_review_matches_the_eventual_owned_attachment_without_creating_state(self):
        result=self.review();self.assertFalse(Path(self.case.settings.state_root).exists())
        self.assertFalse((self.case.root/'unused.ecfg').exists())
        self.assertFalse(result['activation_allowed']);self.assertFalse(result['provider_access'])
        content=dict(result);sha=content.pop('review_sha256');self.assertEqual(digest(content),sha)
        self.case.attach()
        config=result['configuration']['collector']
        self.assertEqual(config['publication_binding'],plain(self.case.session.service.identity))
        self.assertEqual(config['daily_claim'],plain(self.case.session.claim))
        self.assertEqual(config['daily_binding'],plain(self.case.session.binding))

    def test_changed_published_inputs_are_refused_before_driver_or_credential_access(self):
        self.case.r1.write_text(self.case.r1.read_text()+'\n')
        result=self.review()
        self.assertFalse(result['actual_vault_access'])
        self.case.attach()
        original=result['configuration_sha256']
        self.case.r1.write_text(self.case.r1.read_text()+'\n')
        with self.assertRaises(ValueError):self.review()
        self.assertFalse((Path(self.case.settings.state_root)/'driver-state.json').exists())

    def test_catalog_is_bound_to_the_target_date_and_retained_bytes(self):
        self.review()
        p=self.case.root/'catalog/nasdaq.txt';p.write_bytes(p.read_bytes()+b'changed')
        with self.assertRaises(ValueError):self.review()


if __name__=='__main__':unittest.main()
