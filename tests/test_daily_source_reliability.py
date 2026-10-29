"""Source-only readiness and evidence retained across integrity/I/O blocks."""
from contextlib import closing
import json
import sqlite3
import unittest
import os
import time
import shutil
import threading
from pathlib import Path
from datetime import datetime,timedelta
from unittest.mock import patch

import test_daily_source as source_fixtures
import test_daily_operating as operating_fixtures
from test_nasdaq_feed_recovery import rss
from mb_watchlist_coordinator.sampling_service import owner_lock
from mb_watchlist_coordinator.sampling_requests import digest
from mb_watchlist_coordinator.daily_supervision import unseal,read_json


class DailySourceReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.fixture=source_fixtures.DailySourceTests('runTest')
        self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.case=self.fixture.case;self.pump=self.fixture.pump
        self.receipt=self.case.session.root/'daily-source-failure.json'

    def io_error(self):
        error=sqlite3.OperationalError('injected disk I/O error')
        error.sqlite_errorcode=sqlite3.SQLITE_IOERR_READ
        error.sqlite_errorname='SQLITE_IOERR_READ'
        return error

    def test_fully_reconciled_source_is_ready_without_claiming_to_manage_a_collector(self):
        self.fixture.establish();self.case.now+=timedelta(seconds=60)
        result=self.fixture.attempt(rss(self.case.now.date(),symbol='NVDA',halt='15:57:30'))
        self.assertTrue(result['discovery_scope_reconciled'],result)
        self.assertTrue(result['local_membership_effective'],result)
        self.assertEqual(result['status'],'READY_WITH_GAPS',result)
        self.assertEqual(result['worker']['status'],'NOT_CONFIGURED')
        self.assertFalse(result['collector_managed'])

    def test_prevalidation_io_failure_is_saved_and_does_not_dispatch_or_retry(self):
        with patch.object(self.case.session,'validate',side_effect=self.io_error()) as validate:
            with self.assertRaises(sqlite3.OperationalError) as raised:self.pump.cycle(synthetic={'chunks':[]})
        result=raised.exception.source_failure_report
        self.assertEqual(result['status'],'BLOCKED',result)
        self.assertEqual(result['sqlite_failure']['errorname'],'SQLITE_IOERR_READ')
        self.assertTrue(result['failure_receipt_saved'])
        saved=json.loads(self.receipt.read_text())
        checked=dict(saved);checksum=checked.pop('content_sha256')
        self.assertEqual(checksum,digest(checked))
        self.assertEqual(saved['report']['sqlite_failure'],result['sqlite_failure'])
        self.assertEqual(saved['daily_binding_sha256'],self.case.session.binding['binding_sha256'])
        self.assertFalse(self.pump.transport.snapshot()['attempts'])
        self.assertFalse(self.case.calls)
        validate.assert_called_once()

    def test_restoring_old_publication_snapshot_blocks_with_exact_prefix_evidence(self):
        publication=self.case.session.service.path
        original=publication.read_bytes()
        self.fixture.establish()
        before=self.case.store.membership_revisions_in_effective_order()
        self.assertEqual(len(before),3)
        with closing(sqlite3.connect(publication)) as c:
            kinds=[json.loads(row[0])['kind'] for row in c.execute('SELECT payload FROM publication_event ORDER BY sequence')]
            self.assertIn('plan',kinds);self.assertIn('acknowledged',kinds)
        # Deliberate quiescent rollback: healthy SQLite bytes, older valid history.
        with owner_lock(self.case.session.service.lock_path):publication.write_bytes(original)
        with self.assertRaisesRegex(ValueError,'Journal prefix differs') as raised:
            self.pump.cycle(synthetic={'chunks':[]})
        result=raised.exception.source_failure_report
        self.assertEqual(result['status'],'BLOCKED',result)
        self.assertEqual(result['reasons'],['ValueError'])
        d=result['publication_prefix']
        self.assertEqual(d['publication_outcome_count'],0)
        self.assertEqual(d['expected_revision_count'],2)
        self.assertEqual(d['actual_revision_count'],3)
        self.assertEqual(d['first_difference_index'],2)
        self.assertIsNone(d['expected_revision'])
        self.assertEqual(d['actual_revision'],2)
        self.assertEqual(self.case.store.membership_revisions_in_effective_order(),before)
        self.assertEqual(len(self.pump.transport.snapshot()['attempts']),2)
        self.assertEqual(self.case.calls,[['NVDA']])
        self.assertTrue(result['failure_receipt_saved'])
        with closing(sqlite3.connect(publication)) as c:
            self.assertEqual(c.execute('PRAGMA quick_check').fetchone()[0],'ok')
            self.assertEqual(c.execute('SELECT count(*) FROM publication_event').fetchone()[0],0)

    def test_failure_receipt_survives_unreadable_source_status_database(self):
        self.pump.authority.path.write_bytes(b'not a SQLite database')
        result=self.pump.cycle(synthetic={'chunks':[]})
        self.assertEqual(result['status'],'BLOCKED')
        self.assertFalse(result['status_persisted'])
        self.assertEqual(result['sqlite_failure']['errorname'],'SQLITE_NOTADB')
        self.assertTrue(result['failure_receipt_saved'])
        self.assertEqual(json.loads(self.receipt.read_text())['report']['sqlite_failure'],result['sqlite_failure'])

    def test_receipt_write_failure_keeps_original_io_block_and_code(self):
        with patch.object(self.case.session,'validate',side_effect=self.io_error()),patch(
                'mb_watchlist_coordinator.daily_source.atomic_json',side_effect=OSError('injected diagnostic write failure')):
            with self.assertRaises(sqlite3.OperationalError) as raised:self.pump.cycle(synthetic={'chunks':[]})
        result=raised.exception.source_failure_report
        self.assertEqual(result['status'],'BLOCKED')
        self.assertEqual(result['sqlite_failure']['errorname'],'SQLITE_IOERR_READ')
        self.assertFalse(result['failure_receipt_saved'])
        self.assertEqual(result['failure_receipt_error_type'],'OSError')
        self.assertFalse(self.pump.transport.snapshot()['attempts'])

    def test_unowned_closed_pump_still_refuses_before_writing_diagnostic_state(self):
        self.pump.close()
        with self.assertRaises(ValueError):self.pump.cycle(synthetic={'chunks':[]})
        self.assertFalse(self.receipt.exists())


class DailyPacedSourceOwnerTests(unittest.TestCase):
    def test_three_real_paced_feed_children_reconcile_while_owned_hot_collection_continues(self):
        fixture=operating_fixtures.DailyOperatingTests('test_read_only_status_does_not_create_a_missing_outer')
        fixture.setUp();self.addCleanup(fixture.doCleanups)
        case=fixture.case
        scene=json.loads(fixture.scene.read_text())
        scene['feed_body']=rss(fixture.fixture.logical.date(),symbol='NVDA',halt='09:59:00').decode()
        # Admission comes only from the actual owned synthetic feed child.
        scene['admit']=False;fixture.scene.write_text(json.dumps(scene))
        scene['trace_stacks']=True;fixture.scene.write_text(json.dumps(scene))
        auth_scene=json.loads(fixture.fixture.scenario_path.read_text());auth_scene['trace_stacks']=True
        fixture.fixture.scenario_path.write_text(json.dumps(auth_scene))
        owner=fixture.owner();began=time.monotonic();cutover={};result=None
        samples=[time.monotonic()];done=threading.Event()
        def observe():
            while not done.wait(.02):samples.append(time.monotonic())
        observer=threading.Thread(target=observe,daemon=True);observer.start()
        proof={'contract':'daily-paced-source-owned-collection-proof-v1','result':'FAILED',
            'network':'denied','synthetic_sdk_only':True,'actual_vault_access':False,
            'provider_capacity_qualified':False,'full_day_capacity_qualified':False}
        def count():
            with closing(sqlite3.connect(case.journal.resolve().as_uri()+'?mode=ro',uri=True)) as c:
                return c.execute("SELECT count(*) FROM quote_acquisition WHERE channel='hot'").fetchone()[0]
        def stop():
            if time.monotonic()-began>=150:return True
            path=Path(fixture.fixture.config.publication.state_root)/'hot-status.json'
            if not path.exists():return False
            status=unseal(read_json(path))
            if status['source_reconciled'] and not cutover:
                cutover.update(observed_at_utc=status['observed_at_utc'],
                    source_status=status['source_status'],acquisitions=count(),
                    elapsed_seconds=time.monotonic()-began)
            return bool(cutover and count()>=cutover['acquisitions']+2)
        try:
            print('Paced source proof: actual 60-second intervals; CURRENT, history, fresh CURRENT.',flush=True)
            result=owner.run(fixture.secret(),stop_requested_callback=stop)
            proof.update(owner=result,elapsed_seconds=time.monotonic()-began,cutover=cutover)
            self.assertEqual(result['result'],'STOPPED',result)
            self.assertEqual(result['stop_reason'],'operator_stop',result)
            self.assertEqual(result['cleanup']['status'],'EXIT_OBSERVED',result)
            self.assertTrue(cutover,proof)
            self.assertEqual(cutover['source_status'],'READY_WITH_GAPS',proof)
            self.assertGreaterEqual(cutover['elapsed_seconds'],120)
            self.assertTrue(result['reporting']['native_audit_passed'],result)
            self.assertTrue(result['reporting']['two_fresh_replays_equal'],result)
            self.assertGreaterEqual(count(),cutover['acquisitions']+2)
            state=Path(fixture.fixture.config.publication.state_root)
            with closing(sqlite3.connect((state/'daily-feed.sqlite3').as_uri()+'?mode=ro',uri=True)) as c:
                events=[json.loads(row[0]) for row in c.execute('SELECT payload FROM feed_event ORDER BY sequence')]
            starts=[e for e in events if e['kind']=='start'];finishes=[e for e in events if e['kind']=='finish']
            self.assertEqual(len(starts),3,events);self.assertEqual(len(finishes),3,events)
            self.assertEqual(starts[0]['query_id'],'CURRENT');self.assertNotEqual(starts[1]['query_id'],'CURRENT')
            self.assertEqual(starts[2]['query_id'],'CURRENT')
            intervals=[(datetime.fromisoformat(starts[i+1]['at_utc'])-
                datetime.fromisoformat(finishes[i]['at_utc'])).total_seconds() for i in range(2)]
            self.assertTrue(all(n>=60 for n in intervals),intervals)
            self.assertTrue(all(e['outcome']['status']=='valid' and e['unknown'] is None for e in finishes))
            with closing(sqlite3.connect((state/'identity.sqlite3').as_uri()+'?mode=ro',uri=True)) as c:
                identity_events=[json.loads(row[0]) for row in c.execute('SELECT payload FROM identity_event ORDER BY sequence')]
            permits=sum(e.get('kind')=='reservation' for e in identity_events)
            self.assertEqual(permits,1,identity_events)
            driver=unseal(read_json(state/'driver-state.json'))
            self.assertEqual(len(driver['starts']),1,driver)
            self.assertIsNone(driver['terminal'],driver)
            with closing(sqlite3.connect(case.journal.as_uri()+'?mode=ro',uri=True)) as c:
                self.assertEqual(c.execute("SELECT count(*) FROM poll_run WHERE run_id IN ('existing-uni','existing-focus')").fetchone()[0],2)
            self.assertFalse((state/'daily-source-failure.json').exists())
            proof.update(result='PASS',source_attempts=3,source_query_ids=[e['query_id'] for e in starts],
                completion_to_next_start_seconds=intervals,identity_quote_permits=permits,
                native_hot_acquisitions=count(),acquisitions_after_reconciliation=count()-cutover['acquisitions'],
                worker_starts=1,native_audit_passed=True,two_fresh_replays_equal=True,
                source_reconciled=True,actual_elapsed_pacing=True,production_changes=False)
        finally:
            done.set();observer.join(timeout=1)
            proof['max_observer_scheduling_gap_seconds']=max((b-a for a,b in zip(samples,samples[1:])),default=0)
            dest=os.environ.get('MB_DAILY_PACED_SOURCE_PROOF_DIR')
            if dest:
                dest=Path(dest);dest.mkdir(parents=True,exist_ok=False)
                (dest/'proof.json').write_text(json.dumps(proof,indent=2)+'\n')
                if result and result['cleanup']['status']=='EXIT_OBSERVED':
                    shutil.copytree(case.root,dest/'closed-state')
                    (dest/'FORENSIC_COPY.txt').write_text('Closed synthetic evidence retains original temporary path identities. Do not adopt as live state.\n')


if __name__=='__main__':unittest.main()
