"""Bounded public daily composition; synthetic inputs and denied network only."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

import test_daily_session as fixtures
from mb_watchlist_coordinator import daily_launch as launch
from mb_watchlist_coordinator import market_open_check as check
from mb_watchlist_coordinator.authenticated_startup import SessionPassword
from mb_watchlist_coordinator.daily_feed import collection_feed_limits
from mb_watchlist_coordinator.sampling_requests import digest
from mb_watchlist_coordinator.daily_supervision import read_json, unseal

DEPENDENCIES={'qualified':True,'reason':'offline_daily_check_fixture'}
SECRET='SYNTHETIC-DAILY-PATH-PRIVATE-CANARY'


class FixtureDate(datetime):
    @classmethod
    def now(cls,tz=None):
        return datetime(2026,10,29,18,tzinfo=ZoneInfo('America/New_York')).astimezone(tz)


class MarketOpenCheckTests(unittest.TestCase):
    def setUp(self):
        self.case=fixtures.DailySessionTests('test_preview_reads_published_anchor_and_creates_no_application_state_or_client')
        if self._testMethodName=='test_owned_public_dispatch_collects_then_reports_after_producer_exit':
            self.case.proof_directory_override=os.environ.get('MB_MARKET_OPEN_CHECK_PROOF')
        with patch.object(fixtures,'datetime',FixtureDate):self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.source=self.case.root/'packet with spaces'
        coordinator=self.source/'coordinator/src/mb_watchlist_coordinator'
        shutil.copytree(Path(launch.__file__).parent,coordinator,ignore=shutil.ignore_patterns('__pycache__'))
        self.patch=patch.object(launch,'__file__',str(coordinator/'daily_launch.py'))
        self.patch.start();self.addCleanup(self.patch.stop)
        self.root=self.source/'runs/market_open_daily_20261030_1234abcd'
        self.clock=lambda:self.case.now
        self.inventory()

    def inventory(self):
        files={p.relative_to(self.source).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(self.source.rglob('*')) if p.is_file() and p.name!='SOURCE_INVENTORY.json'
            and 'runs' not in p.relative_to(self.source).parts}
        (self.source/'SOURCE_INVENTORY.json').write_text(json.dumps({'files':files}))

    def prepare(self):
        return check.prepare_trial(str(self.source),str(self.root),str(self.case.r0),str(self.case.r1),
            self.case.catalog,clock=self.clock)

    def review(self):
        return check.build_trial_review(str(self.source),str(self.root),str(self.case.root/'unused.ecfg'),
            clock=self.clock,dependency_reader=lambda _:DEPENDENCIES)

    def invoke(self,review,**kwargs):
        options=dict(trial_approved=True,market_open_confirmed=True,clock=self.clock,
            dependency_reader=lambda _:DEPENDENCIES)
        options.update(kwargs)
        return check.run_trial(review,**options)

    def test_prepare_copies_exact_proposals_and_never_opens_the_production_journal_or_ecfg(self):
        before=self.case.journal.read_bytes();original=[self.case.r0.read_bytes(),self.case.r1.read_bytes()]
        prepared=self.prepare()
        self.assertEqual(self.case.journal.read_bytes(),before)
        self.assertEqual([Path(p).read_bytes() for p in prepared['copied_inputs'].values()],original)
        self.assertFalse(Path(self.case.settings.state_root).exists())
        self.assertFalse((self.case.root/'unused.ecfg').exists())
        with closing(sqlite3.connect(prepared['journal_path'])) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM quote_acquisition').fetchone()[0],0)
            for raw, in c.execute('SELECT configuration_json FROM poll_run'):
                self.assertTrue(json.loads(raw)['context_only'])

    def test_existing_or_partial_trial_is_retained_and_refused(self):
        self.prepare();marker=self.root/'keep';marker.write_text('retained')
        with self.assertRaises(ValueError):self.prepare()
        self.assertEqual(marker.read_text(),'retained')

    def test_prepare_rejects_an_escaped_output_path_before_creating_files(self):
        with self.assertRaises(ValueError):
            check.prepare_trial(str(self.source),str(self.case.root/'market_open_daily_20261030_1234abcd'),
                str(self.case.r0),str(self.case.r1),self.case.catalog,clock=self.clock)
        self.assertFalse(self.root.exists())

    def test_review_preserves_fixed_daily_entries_and_binds_the_short_window(self):
        self.prepare();review=self.review();check.validate_trial_review(review,clock=self.clock)
        public=review['launch_review'];config=public['backend_review']['configuration']
        self.assertEqual(config['collector']['max_quote_calls'],72)
        self.assertEqual(datetime.fromisoformat(config['collector']['stop_at_utc'])-
            datetime.fromisoformat(config['collector']['start_at_utc']),timedelta(seconds=180))
        self.assertEqual(public['backend_review']['collection_feed_limits']['max_attempts'],4)
        for role,command in public['commands'].items():
            self.assertEqual(command[3],str(self.source/'coordinator/src/mb_watchlist_coordinator/daily_launch_entry.py'))
            self.assertEqual(command[4],role)
        self.assertFalse((self.root/'daily_hot_check').exists())
        self.assertFalse((self.root/'daily_outer_check').exists())

    def test_recheck_rebuilds_the_bounded_configuration_without_restoring_all_day_limits(self):
        self.prepare();public=self.review()['launch_review']
        config=launch.recheck_review(public,clock=self.clock,dependency_reader=lambda _:DEPENDENCIES)
        self.assertEqual(config.collector.max_quote_calls,72)
        self.assertEqual(collection_feed_limits(config.collector).budget_seconds,180)

    def test_default_all_day_review_and_source_limits_are_unchanged(self):
        from mb_watchlist_coordinator.daily_operating_review import build_operating_review
        result=build_operating_review(str(self.case.r0),str(self.case.r1),journal=str(self.case.journal),
            catalog=str(self.case.catalog.path),state_root=self.case.settings.state_root,
            ecfg=str(self.case.root/'unused.ecfg'),clock=self.clock)
        config=launch.configuration(result['configuration'])
        self.assertEqual(config.collector.max_quote_calls,9360)
        self.assertEqual(collection_feed_limits(config.collector).max_attempts,390)
        self.assertEqual(collection_feed_limits(config.collector).budget_seconds,23400)
        self.assertNotIn('collection_window',result)

    def test_missing_trial_approval_or_market_confirmation_prevents_the_password_prompt(self):
        self.prepare();review=self.review()
        for field in ('trial_approved','market_open_confirmed'):
            with patch.object(SessionPassword,'prompt') as prompt:
                with self.assertRaises(ValueError):self.invoke(review,**{field:False})
                prompt.assert_not_called()
        self.assertFalse((self.root/'approved-trial-review.json').exists())

    def test_rehashed_longer_window_or_larger_budget_is_refused_before_password(self):
        self.prepare();original=self.review()
        for field,value in (('max_quote_calls',73),('stop_at_utc',(self.case.now+timedelta(seconds=181)).isoformat())):
            review=json.loads(json.dumps(original))
            review['launch_review']['backend_review']['configuration']['collector'][field]=value
            content=dict(review);content.pop('review_sha256');review['review_sha256']=digest(content)
            with patch.object(SessionPassword,'prompt') as prompt:
                with self.assertRaises(ValueError):self.invoke(review)
                prompt.assert_not_called()

    def test_mid_prompt_expiry_clears_secret_and_does_not_launch_an_owner(self):
        self.prepare();review=self.review();secret=SessionPassword(SECRET,review['launch_review']['configuration_sha256'])
        def prompt(_):self.case.now+=timedelta(seconds=181);return secret
        with patch.object(launch,'DailyOperatingOwner') as owner:
            with self.assertRaises(ValueError):self.invoke(review,prompt=prompt)
        self.assertFalse(secret._value);self.assertFalse((self.root/'daily_outer_check').exists())

    def test_mid_prompt_input_change_keeps_existing_rechecks_and_secret_cleanup(self):
        self.prepare();review=self.review();secret=SessionPassword(SECRET,review['launch_review']['configuration_sha256'])
        def prompt(_):
            (self.root/'inputs/focus-r1.json').write_text('{}');return secret
        with self.assertRaises(ValueError):self.invoke(review,prompt=prompt)
        self.assertFalse(secret._value);self.assertFalse((self.root/'daily_outer_check').exists())

    def test_approved_trial_passes_exact_review_and_secret_to_the_existing_owner(self):
        self.prepare();review=self.review();seen={}
        class Owner:
            def __init__(self,root,config,**kwargs):
                self.binding={};seen.update(root=root,config=config,options=kwargs,binding=self.binding)
            def run(self,secret,**kwargs):
                seen['private_secret_matches']=bytes(secret._value)==SECRET.encode();return {'result':'STOPPED'}
        secret=SessionPassword(SECRET,review['launch_review']['configuration_sha256'])
        self.assertEqual(self.invoke(review,prompt=lambda _:secret,owner_factory=Owner)['result'],'STOPPED')
        self.assertEqual(seen['binding']['public_launch']['review'],review['launch_review'])
        self.assertEqual(seen['config'].collector.max_quote_calls,72)
        self.assertTrue(seen['private_secret_matches']);self.assertFalse(secret._value)

    def test_weekend_closed_and_near_close_windows_are_refused(self):
        for at in (self.case.now.replace(hour=9,minute=29),self.case.now.replace(hour=16),
                   self.case.now.replace(hour=15,minute=58),self.case.now+timedelta(days=1)):
            with self.subTest(at=at),self.assertRaises(ValueError):check.market_window(at)
        # EST after the weekend is derived from ET, not a hardcoded UTC offset.
        after=datetime(2026,11,2,9,30,tzinfo=ZoneInfo('America/New_York'))
        self.assertEqual(check.market_window(after),after.date())
        self.assertEqual(after.astimezone(timezone.utc).hour,14)

    def test_modified_prepared_copy_is_refused_without_opening_credentials(self):
        self.prepare();(self.root/'inputs/opening-r0.json').write_text('{}')
        with patch.object(SessionPassword,'prompt') as prompt:
            with self.assertRaises(ValueError):self.review()
            prompt.assert_not_called()

    def test_quiet_description_does_not_claim_admission_or_all_day_qualification(self):
        description=check.describe()
        self.assertFalse(description['production_hot_enabled'])
        self.assertFalse(description['operating_release_qualified'])
        self.assertIn('unobserved',description['quiet_run'])

    def test_bounded_feed_budget_and_original_pacing_survive_readonly_reopen(self):
        from mb_watchlist_coordinator.daily_feed import DailyFeedTransport
        from mb_watchlist_coordinator.nasdaq_recovery import RecoveryQuery
        from mb_watchlist_coordinator.nasdaq_feed_recovery import query_url
        self.prepare();config=launch.configuration(self.review()['launch_review']['backend_review']['configuration'])
        limits=collection_feed_limits(config.collector)
        feed=DailyFeedTransport(self.root/'feed-boundary.sqlite3',session_date=self.case.now.date(),
            queries=(RecoveryQuery(self.case.now.date(),self.case.now.date()),),limits=limits,clock=self.clock)
        feed.initialize(create=True)
        body=b'<?xml version="1.0"?><rss version="2.0"><channel><title>Nasdaq Trade Halts</title></channel></rss>'
        for index in range(3):
            reservation=feed.reserve(synthetic=True);self.assertIsNotNone(reservation)
            self.case.now+=timedelta(milliseconds=100)
            feed.progress(reservation,{'status_code':200,'final_url':query_url(),
                'headers':{'Content-Length':str(len(body))},'body_complete':True},body)
            feed.finish(reservation)
            self.assertIsNone(feed.reserve(synthetic=True)) # same-minute extra call is refused
            self.case.now+=timedelta(seconds=60)
        before=feed.path.read_bytes()
        reopened=DailyFeedTransport(feed.path,session_date=feed.session_date,queries=feed.queries,
            limits=limits,clock=self.clock)
        self.assertEqual(len(reopened.snapshot()['attempts']),3)
        self.assertIsNone(reopened.reserve(synthetic=True)) # original 180-second budget ended
        self.assertEqual(feed.path.read_bytes(),before)

    def test_owned_public_dispatch_collects_then_reports_after_producer_exit(self):
        import mb_market_data
        native=Path(mb_market_data.__file__).resolve().parents[1]
        shutil.copytree(native,self.source/'market_data/src',ignore=shutil.ignore_patterns('__pycache__'))
        # The real fixed entry is executed in every owned role. Only subprocess
        # construction in this offline fixture adds a trusted injection wrapper.
        fixture=Path(__file__).parent/'fixtures/market_open_daily_process.py'
        delivered=self.source/'coordinator/tests/fixtures/market_open_daily_process.py'
        delivered.parent.mkdir(parents=True);shutil.copyfile(fixture,delivered)
        self.inventory();self.prepare()
        real=datetime.now(timezone.utc);logical=self.case.now
        self.clock=lambda:logical+(datetime.now(timezone.utc)-real)
        review=self.review();scene=self.root/'offline-scene.json'
        log=self.root/'offline-roles.jsonl'
        scene.write_text(json.dumps({'real_anchor':real.isoformat(),'logical_anchor':logical.isoformat(),
            'log':str(log),'dependencies':DEPENDENCIES}))
        entry=str(self.source/'coordinator/src/mb_watchlist_coordinator/daily_launch_entry.py')
        popen=subprocess.Popen
        def wrapped(command,*a,**kw):
            command=list(command)
            if len(command)>3 and command[3]==entry:
                command=[*command[:3],str(delivered),str(scene),entry,*command[4:]]
            return popen(command,*a,**kw)
        secret=SessionPassword(SECRET,review['launch_review']['configuration_sha256'])
        began=time.monotonic()
        def stop():
            if time.monotonic()-began>70:return True
            with closing(sqlite3.connect(self.root/f'quote_observation_journal_v2_api_opening_{logical.date()}'/f'{logical.date()}.sqlite3')) as c:
                return c.execute('SELECT count(*) FROM quote_acquisition WHERE channel="hot"').fetchone()[0]>=2
        with patch('subprocess.Popen',wrapped):owner=self.invoke(review,prompt=lambda _:secret,stop_requested_callback=stop)
        self.assertFalse(secret._value)
        report=check.summarize_trial(str(self.source),str(self.root),clock=self.clock)
        (self.root/'offline-proof.json').write_text(json.dumps({'owner':owner,'report':report},indent=2))
        self.assertEqual(owner['result'],'STOPPED',owner)
        self.assertEqual(owner['stop_reason'],'operator_stop',owner)
        self.assertTrue(check._empty_scope(owner['cleanup']),owner)
        self.assertTrue(check._empty_scope(owner['reporting']['cleanup']),owner)
        self.assertTrue(owner['reporting']['native_audit_passed'],owner)
        self.assertTrue(owner['reporting']['two_fresh_replays_equal'],owner)
        self.assertEqual(report['hot_acquisitions'],2,report)
        self.assertTrue(report['collection_observed'])
        self.assertEqual(report['authenticated_roles'],['collector','identity'])
        # Stopping early after two samples cannot qualify the complete trial or
        # its three paced source captures, even with good quotes/audit/replays.
        self.assertEqual(report['result'],'INCOMPLETE')
        roles={json.loads(line)['role'] for line in log.read_text().splitlines()}
        self.assertTrue({'controller','collector','identity','reporter'}<=roles,roles)
        self.assertNotIn(SECRET,log.read_text())


if __name__=='__main__':unittest.main()
