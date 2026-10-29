"""Compact identity keeps the exact original catalog and admission rules."""
import os
import unittest

import test_daily_session as fixture
from mb_watchlist_coordinator.daily_admission import DailyAdmissionPolicy
from mb_watchlist_coordinator.sampling_requests import digest


class DailyAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.case=fixture.DailySessionTests('test_preview_reads_published_anchor_and_creates_no_application_state_or_client')
        self.case.setUp();self.addCleanup(self.case.doCleanups)

    def policy(self):
        return DailyAdmissionPolicy(self.case.catalog.catalog_id,frozenset(self.case.catalog.symbols),
            frozenset({'nasdaq-shared-daily'}),1,'session')

    def test_compact_descriptor_binds_every_symbol_and_does_not_expose_mutable_cached_values(self):
        p=self.policy();value=p.payload()
        self.assertNotIn('catalog_symbols',value)
        self.assertEqual(value['catalog_symbols_sha256'],digest(sorted(self.case.catalog.symbols)))
        self.assertEqual(value['catalog_symbol_count'],len(self.case.catalog.symbols))
        self.assertEqual(p.catalog_symbols,frozenset(self.case.catalog.symbols))
        value['allowed_sources'].append('untrusted')
        self.assertEqual(p.payload()['allowed_sources'],['nasdaq-shared-daily'])

    def test_changed_set_source_or_boolean_limit_is_rejected_before_serialization(self):
        for name,value in (('catalog_symbols',frozenset({'OTHER'})),('allowed_sources',frozenset({'untrusted'})),
                           ('max_additional_symbols',True)):
            with self.subTest(name=name):
                p=self.policy();object.__setattr__(p,name,value)
                with self.assertRaises(ValueError):p.payload()

    def test_outside_catalog_is_not_quoted_and_normal_catalog_admission_still_succeeds(self):
        self.case.attach()
        self.case.admit('OUTSIDE',capture='outside')
        self.assertFalse(self.case.calls)
        gate=self.case.session.gate.snapshot()['identity_gate']
        self.assertIn('catalog_unresolved',gate['dispositions'].values())
        self.case.admit('NVDA',capture='inside')
        self.assertEqual(self.case.calls,[['NVDA']])
        self.assertEqual(self.case.store.membership_revisions_in_effective_order()[-1].hot_symbols,('NVDA',))

    def test_catalog_digest_reuse_still_reads_same_length_same_mtime_source_bytes(self):
        c=self.case.catalog
        self.assertEqual(c.verified_public_sha256(),digest(c.public))
        path=c.path/'nasdaq.txt';before=path.stat();raw=path.read_bytes()
        changed=raw.replace(b'NVDA|Nvidia',b'NVDA|NVidIa')
        self.assertEqual(len(raw),len(changed));path.write_bytes(changed)
        os.utime(path,ns=(before.st_atime_ns,before.st_mtime_ns))
        with self.assertRaises(ValueError):c.verified_public_sha256()


if __name__=='__main__':unittest.main()
