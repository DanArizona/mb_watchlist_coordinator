from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import time
import unittest
from zoneinfo import ZoneInfo

from mb_watchlist_coordinator.integrated_catalog import (
    SOURCES, CatalogError, DirectoryCatalog, acquire_catalog)
from mb_watchlist_coordinator.sampling_requests import plain, utc_text

AT = (datetime.now(ZoneInfo('America/New_York'))+timedelta(days=1)).replace(
    hour=10, minute=0, second=0, microsecond=0)


def sources(at=AT):
    footer = at.replace(hour=9).strftime('%m%d%Y%H:%M')
    return {'nasdaq': ('Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF\n'
        'MSFT|Microsoft|Q|N|N|100|N\nNVDA|Nvidia|Q|N|N|100|N\nAMD|AMD|Q|N|N|100|N\n'
        'SPY|ETF|G|N|N|100|Y\nTEST|Test|G|Y|N|100|N\n'
        'File Creation Time: '+footer+'||||||\n').encode(),
        'other': ('ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol\n'
        'IBM|IBM|N|IBM|N|100|N|IBM\n'
        'ALIAS|Alias|N|ALIAS.A|N|100|N|ALIAS\n'
        'BRK.B|Punctuation|N|BRK.B|N|100|N|BRK.B\n'
        'File Creation Time: '+footer+'|||||||\n').encode()}


def receipts(at=AT, synthetic=True):
    return {label: {'url': url, 'started_at_utc': utc_text(at), 'retrieved_at_utc': utc_text(at),
        'synthetic': synthetic, 'http': {'status': 200, 'final_url': url, 'body_complete': True}}
        for label, url in SOURCES.items()}


def catalog(at=AT):
    return DirectoryCatalog(sources(at), receipts(at))


class CatalogTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_exact_catalog_excludes_tests_etfs_punctuation_and_ambiguous_aliases(self):
        result = catalog()
        self.assertEqual(result.symbols, ('AMD', 'IBM', 'MSFT', 'NVDA'))
        self.assertEqual(set(result.public['sources']), set(SOURCES))
        self.assertTrue(result.public['sources']['nasdaq']['synthetic'])

    def test_catalog_is_not_a_daily_price_volume_or_cap_screen(self):
        self.assertIn('NVDA', catalog().symbols)
        self.assertIn('not_daily_screen', catalog().public['scope'])

    def test_raw_hash_and_receipt_time_change_catalog_identity(self):
        a = catalog(); b = sources(); b['nasdaq'] += b'\n'
        self.assertNotEqual(a.catalog_id, DirectoryCatalog(b, receipts()).catalog_id)
        r = receipts(); r['other']['retrieved_at_utc'] = utc_text(AT+timedelta(seconds=1))
        self.assertNotEqual(a.catalog_id, DirectoryCatalog(sources(), r).catalog_id)

    def test_duplicate_symbol_across_sources_is_rejected(self):
        b = sources(); b['other'] = b['other'].replace(b'IBM|IBM|N|IBM|N|100|N|IBM', b'MSFT|Other|N|MSFT|N|100|N|MSFT')
        with self.assertRaises(CatalogError): DirectoryCatalog(b, receipts())

    def test_html_missing_footer_and_bad_columns_are_not_empty_catalogs(self):
        for body in (b'<html>challenge</html>', sources()['nasdaq'].split(b'File Creation')[0],
                sources()['nasdaq'].replace(b'MSFT|Microsoft|Q|N|N|100|N', b'MSFT|bad')):
            b = sources(); b['nasdaq'] = body
            with self.assertRaises(CatalogError): DirectoryCatalog(b, receipts())

    def test_invalid_yes_no_and_duplicate_header_are_rejected(self):
        for body in (sources()['nasdaq'].replace(b'MSFT|Microsoft|Q|N|N|100|N', b'MSFT|Microsoft|Q|X|N|100|N'),
                sources()['nasdaq'].replace(b'|ETF\n', b'|Symbol\n')):
            b = sources(); b['nasdaq'] = body
            with self.assertRaises(CatalogError): DirectoryCatalog(b, receipts())

    def test_footer_must_be_last_and_unique(self):
        for suffix in (b'MORE|Row|Q|N|N|100|N\n', sources()['nasdaq'].splitlines()[-1]+b'\n'):
            b = sources(); b['nasdaq'] += suffix
            with self.assertRaises(CatalogError): DirectoryCatalog(b, receipts())

    def test_future_or_stale_footer_is_rejected_and_prior_close_is_allowed(self):
        old = AT.replace(hour=9).strftime('%m%d%Y%H:%M').encode()
        for replacement in (AT+timedelta(days=1), AT-timedelta(days=8)):
            b = sources(); b['nasdaq'] = b['nasdaq'].replace(old, replacement.strftime('%m%d%Y%H:%M').encode())
            with self.assertRaises(CatalogError): DirectoryCatalog(b, receipts())
        b = sources(); b['nasdaq'] = b['nasdaq'].replace(old, (AT-timedelta(days=1)).strftime('%m%d%Y%H:%M').encode())
        self.assertIn('MSFT', DirectoryCatalog(b, receipts()).symbols)

    def test_non_200_redirect_and_incomplete_metadata_are_rejected(self):
        for key, value in (('status', 503), ('status', True), ('final_url', 'https://other.invalid'), ('body_complete', False)):
            r = receipts(); r['nasdaq']['http'][key] = value
            with self.assertRaises(CatalogError): DirectoryCatalog(sources(), r)

    def test_negative_or_overlong_retrieval_clock_is_rejected(self):
        for seconds in (-1, 11):
            r = receipts(); r['nasdaq']['retrieved_at_utc'] = utc_text(AT+timedelta(seconds=seconds))
            with self.assertRaises(CatalogError): DirectoryCatalog(sources(), r)

    def test_persist_and_reopen_revalidate_raw_bytes_and_identity(self):
        original = catalog(); saved = original.persist(self.root/'catalog')
        self.assertEqual(saved.catalog_id, original.catalog_id)
        self.assertEqual(DirectoryCatalog.load(saved.path).symbols, original.symbols)
        (saved.path/'nasdaq.txt').write_bytes(sources()['nasdaq']+b'\n')
        with self.assertRaises(CatalogError): saved.validate()

    def test_changed_manifest_and_missing_artifact_block_reopen(self):
        saved = catalog().persist(self.root/'catalog')
        p = saved.path/'catalog.json'; d = json.loads(p.read_text()); d['public']['symbols'].append('FAKE'); p.write_text(json.dumps(d))
        with self.assertRaises(CatalogError): DirectoryCatalog.load(saved.path)
        (saved.path/'other.txt').unlink()
        with self.assertRaises(CatalogError): DirectoryCatalog.load(saved.path)

    def test_fresh_catalog_never_overwrites_existing_folder(self):
        saved = catalog().persist(self.root/'catalog')
        with self.assertRaises(FileExistsError): catalog().persist(saved.path)

    def test_two_owned_synthetic_retrievals_capture_fixed_urls_without_network(self):
        scenario = {k: {'body': v.decode()} for k, v in sources().items()}
        result = acquire_catalog(deadline=AT+timedelta(seconds=50), clock=lambda: AT, synthetic=scenario)
        self.assertEqual(result.symbols, catalog().symbols)
        self.assertFalse(list(self.root.iterdir()))

    def test_network_requires_explicit_authorization(self):
        with self.assertRaises(CatalogError): acquire_catalog(deadline=AT+timedelta(seconds=50), clock=lambda: AT)

    def test_failed_first_child_does_not_spend_second_source_attempt(self):
        scenario = {'nasdaq': {'body': '<html>no feed</html>'}, 'other': {'body': '', 'hang': True}}
        with self.assertRaises(CatalogError) as caught:
            acquire_catalog(deadline=AT+timedelta(seconds=50), clock=lambda: AT, synthetic=scenario)
        self.assertEqual({r['source'] for r in caught.exception.receipts}, {'nasdaq'})
        self.assertEqual(caught.exception.receipts[0]['body_bytes'], len(b'<html>no feed</html>'))
        self.assertIn('body_b64', caught.exception.receipts[0])

    def test_hanging_owned_child_has_hard_deadline_and_observed_exit(self):
        scenario = {k: {'body': v.decode(), 'hang': True} for k, v in sources().items()}
        began = time.monotonic()
        with self.assertRaises(CatalogError) as caught:
            acquire_catalog(deadline=AT+timedelta(seconds=50), clock=lambda: AT, synthetic=scenario, hard_seconds=.4)
        self.assertLess(time.monotonic()-began, 5)
        self.assertTrue(caught.exception.receipts[-1]['owned_child_exit_observed'])
        self.assertEqual(caught.exception.code, 'catalog_hard_deadline')
        self.assertEqual({r['source'] for r in caught.exception.receipts}, {'nasdaq'})

    def test_expired_or_widened_bootstrap_window_starts_no_child(self):
        for seconds in (0, 62):
            with self.assertRaises(CatalogError) as caught:
                acquire_catalog(deadline=AT+timedelta(seconds=seconds), clock=lambda: AT,
                    synthetic={k: {'body': v.decode()} for k, v in sources().items()})
            self.assertEqual(caught.exception.receipts, ())

    def test_child_redirect_http_error_or_incomplete_body_fails_closed(self):
        for patch in ({'status': 403}, {'final_url': 'https://wrong.invalid'}, {'body_complete': False}):
            scenario = {k: {'body': v.decode()} for k, v in sources().items()}; scenario['nasdaq'].update(patch)
            with self.assertRaises(CatalogError):
                acquire_catalog(deadline=AT+timedelta(seconds=50), clock=lambda: AT, synthetic=scenario)

