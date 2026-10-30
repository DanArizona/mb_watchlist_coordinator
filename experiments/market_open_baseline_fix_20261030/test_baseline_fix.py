"""Synthetic source and failed-attempt files only; no provider or production state."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import unittest
from unittest.mock import patch
from uuid import uuid4
from zoneinfo import ZoneInfo

PACKET=None
HELPER=None
PROOF_ROOT=None


def files(root):
    return {p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file() and p.suffix not in ('.db-wal','.db-shm')
            and not p.name.endswith(('-wal','-shm'))}


class BaselineCopyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        PROOF_ROOT.mkdir(parents=True)
        cls.packet=PROOF_ROOT/'p'
        shutil.copytree(PACKET,cls.packet,ignore=shutil.ignore_patterns('runs','__pycache__'))
        HELPER.configure(cls.packet)

    def setUp(self):
        from mb_market_data.quote_observation_store import QuoteObservationStore
        import mb_market_data.quote_observation_store as native
        from mb_market_data.sampling_membership import SamplingHierarchyRevision
        from test_integrated_catalog import catalog
        self.now=datetime(2026,10,30,10,tzinfo=ZoneInfo('America/New_York'))
        self.published=self.now.replace(hour=9,minute=20)
        day=self.now.date(); self.case=PROOF_ROOT/('c'+uuid4().hex[:6]);self.case.mkdir()
        self.failed=self.packet/'runs'/('market_open_daily_20261030_'+uuid4().hex[:8])
        (self.failed/'inputs').mkdir(parents=True)
        common={'session_date':str(day),'effective_at':self.now.replace(hour=9,minute=30).isoformat(),
            'uni_symbols':['IBM','MSFT'],'hot_symbols':[],'source':'synthetic published opening',
            'metadata':{'synthetic_only':True}}
        self.proposals=[]
        for revision,focus,name in ((0,[],'opening-r0.json'),(1,['MSFT'],'focus-r1.json')):
            raw=dict(common,revision=revision,focus_symbols=focus)
            (self.failed/'inputs'/name).write_text(json.dumps(raw))
            self.proposals.append(SamplingHierarchyRevision(**dict(raw,session_date=day,
                effective_at=datetime.fromisoformat(raw['effective_at']))))
        catalog(self.now.replace(hour=9)).persist(self.failed/'daily_catalog')
        self.journal=self.case/f'quote_observation_journal_v2_api_opening_{day}'/f'{day}.sqlite3'
        self.store=QuoteObservationStore(self.journal,session_date=day,schema_version=2)
        with patch.object(native,'_utc_now',lambda:self.published):
            self.store.initialize()
            for proposal in self.proposals:self.store.record_membership_revision(proposal)
        self.partial=self.failed/f'quote_observation_journal_v2_api_opening_{day}'/f'{day}.sqlite3'
        self.partial_store=QuoteObservationStore(self.partial,session_date=day,schema_version=2)
        self.partial_store.initialize()
        self.export=self.case/'opening.json'
        self.clock=lambda:self.now

    def snapshot(self):
        return HELPER.export_baseline(self.packet,self.failed,self.journal,self.export,clock=self.clock)

    def prepare(self,export=None):
        return HELPER.prepare_from_export(self.packet,self.failed,export or self.export,clock=self.clock)

    def rewritten(self,change):
        from mb_watchlist_coordinator.daily_supervision import unseal
        value=unseal(json.loads(self.export.read_text()));change(value)
        other=self.case/('altered'+uuid4().hex[:4]+'.json');HELPER._write_new(other,value)
        return other

    def test_after_open_copy_preserves_publication_times_and_native_audit(self):
        from mb_market_data.quote_observation_store import QuoteObservationStore
        from mb_market_data.quote_journal_audit import audit_quote_journal
        from mb_watchlist_coordinator import market_open_check as check
        before=self.journal.read_bytes();self.snapshot()
        # Historical import must never invoke the new-publication operation.
        with patch.object(QuoteObservationStore,'record_membership_revision',side_effect=AssertionError('No new publication')):
            prepared=self.prepare()
        store=QuoteObservationStore(prepared['journal_path'],session_date=self.now.date(),schema_version=2)
        revisions=store.membership_revisions_in_effective_order()
        self.assertEqual([r.published_at for r in revisions],[self.published,self.published])
        self.assertEqual([r.content_sha256 for r in revisions],[p.content_sha256 for p in self.proposals])
        self.assertEqual(self.journal.read_bytes(),before)
        self.assertTrue(audit_quote_journal(prepared['journal_path']).passed)
        self.assertEqual(check.load_prepared(str(self.packet),prepared['root']),prepared)
        with closing(sqlite3.connect(prepared['journal_path'])) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM quote_acquisition').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT count(*) FROM quote_observation').fetchone()[0],0)
        (PROOF_ROOT/'after-opening-proof.json').write_text(json.dumps({
            'synthetic_only':True,'preparation_et':self.now.isoformat(),
            'original_publication_et':self.published.isoformat(),
            'original_publication_times_preserved':True,'native_audit_passed':True,
            'new_membership_publication_calls':0,'hot_acquisitions':0,
            'unchanged_original_loader_accepted':True,'new_directory_downloads':0,
            'production_or_provider_access':False,'prepared_root':prepared['root']},indent=2)+'\n')

    def test_export_uses_read_only_connection_and_reads_no_quote_content(self):
        statements=[];connect=sqlite3.connect
        source=self.journal.as_uri()+'?mode=ro'
        def observed(path,*args,**kwargs):
            c=connect(path,*args,**kwargs)
            if str(path).startswith(self.journal.as_uri()):
                self.assertEqual(str(path),source)
                c.set_trace_callback(statements.append)
                def authorize(action,one,two,database,trigger):
                    if action==sqlite3.SQLITE_READ and one in ('quote_acquisition','quote_observation','poll_run'):
                        return sqlite3.SQLITE_DENY
                    return sqlite3.SQLITE_OK
                c.set_authorizer(authorize)
            return c
        before=self.journal.read_bytes()
        with patch.object(sqlite3,'connect',observed):result=self.snapshot()
        self.assertTrue(statements)
        self.assertFalse(result['source_database_written'])
        self.assertFalse(result['quote_or_acquisition_content_read'])
        self.assertEqual(self.journal.read_bytes(),before)

    def test_import_records_current_creation_time_without_a_shifted_live_clock(self):
        import mb_market_data.quote_observation_store as native
        self.snapshot()
        with patch.object(native,'_utc_now',lambda:self.now):prepared=self.prepare()
        with closing(sqlite3.connect(prepared['journal_path'])) as c:
            created=datetime.fromisoformat(c.execute('SELECT created_at_utc FROM store_identity').fetchone()[0])
        self.assertEqual(created,self.now)
        self.assertEqual(prepared['baseline_import']['imported_at_utc'],self.now.astimezone(timezone.utc).isoformat())

    def test_original_new_publication_backdating_guard_remains_active(self):
        from mb_market_data.quote_observation_store import QuoteObservationStore
        from mb_market_data.sampling_membership import SamplingHierarchyRevision,MembershipRevisionError
        import mb_market_data.quote_observation_store as native
        self.snapshot();prepared=self.prepare()
        store=QuoteObservationStore(prepared['journal_path'],session_date=self.now.date(),schema_version=2)
        candidate=SamplingHierarchyRevision(session_date=self.now.date(),revision=2,
            effective_at=self.proposals[1].effective_at,uni_symbols=('IBM','MSFT'),focus_symbols=('MSFT',),
            hot_symbols=(),source='synthetic illegal new backdated revision')
        with patch.object(native,'_utc_now',lambda:self.now),self.assertRaises(MembershipRevisionError):
            store.record_membership_revision(candidate)
        self.assertEqual(len(store.membership_revisions_in_effective_order()),2)

    def test_old_failed_attempt_is_preserved_and_cached_directory_is_copied(self):
        from mb_watchlist_coordinator.integrated_catalog import DirectoryCatalog
        before=files(self.failed);self.snapshot();prepared=self.prepare()
        self.assertEqual(files(self.failed),before)
        self.assertNotEqual(prepared['root'],str(self.failed))
        old=DirectoryCatalog.load(self.failed/'daily_catalog');new=DirectoryCatalog.load(prepared['catalog_path'])
        self.assertEqual(old.public,new.public)
        self.assertFalse((self.failed/'prepared.json').exists())

    def test_rehashed_changed_membership_is_refused_before_new_state(self):
        self.snapshot();before=set((self.packet/'runs').iterdir())
        changed=self.rewritten(lambda v:v['tables']['sampling_channel_member'][0].update(symbol='NVDA'))
        with self.assertRaises((ValueError,RuntimeError)):self.prepare(changed)
        self.assertEqual(set((self.packet/'runs').iterdir()),before)

    def test_rehashed_invalid_original_publication_time_is_refused(self):
        self.snapshot();before=set((self.packet/'runs').iterdir())
        changed=self.rewritten(lambda v:v['tables']['sampling_membership_revision'][0].update(
            published_at_utc=self.now.astimezone(timezone.utc).isoformat()))
        with self.assertRaises(ValueError):self.prepare(changed)
        self.assertEqual(set((self.packet/'runs').iterdir()),before)

    def test_changed_retained_proposal_bytes_are_refused(self):
        self.snapshot();path=self.failed/'inputs/focus-r1.json';path.write_text(path.read_text()+'\n')
        with self.assertRaises(ValueError):self.prepare()
        self.assertTrue(path.read_text().endswith('\n'))

    def test_retained_attempt_with_recorded_history_is_not_reused(self):
        from mb_market_data.quote_observation_store import PollRunProvenance
        self.partial_store.record_run(PollRunProvenance('keep-history',self.now,'synthetic',
            {'watchlist_kind':'uni','poll_seconds':[0,30],'cadence_profile':'interleaved-v1'}))
        before=files(self.failed)
        with self.assertRaises(ValueError):self.snapshot()
        self.assertEqual(files(self.failed),before)
        self.assertFalse(self.export.exists())

    def test_future_or_other_session_export_is_refused(self):
        self.snapshot()
        for change in (lambda v:v.update(exported_at_utc=(self.now+timedelta(seconds=1)).isoformat()),
                       lambda v:v.update(session_date='2026-11-02')):
            changed=self.rewritten(change)
            with self.assertRaises(ValueError):self.prepare(changed)

    def test_existing_export_is_not_overwritten(self):
        self.export.write_text('retain original file')
        with self.assertRaises(ValueError):self.snapshot()
        self.assertEqual(self.export.read_text(),'retain original file')

    def test_unchanged_public_review_accepts_copy_and_retains_trial_limits(self):
        from mb_watchlist_coordinator import daily_launch,market_open_check
        from mb_watchlist_coordinator.sampling_requests import digest
        self.snapshot();prepared=self.prepare()
        with patch.object(daily_launch,'__file__',str(self.packet/'coordinator/src/mb_watchlist_coordinator/daily_launch.py')):
            review=market_open_check.build_trial_review(str(self.packet),prepared['root'],
                str(self.case/'unused.ecfg'),clock=self.clock,
                dependency_reader=lambda _: {'qualified':True,'reason':'synthetic baseline test'})
            market_open_check.validate_trial_review(review,clock=self.clock)
        self.assertEqual(review['prepared_sha256'],digest(prepared))
        collector=review['launch_review']['backend_review']['configuration']['collector']
        self.assertEqual(collector['max_quote_calls'],72)
        self.assertEqual(datetime.fromisoformat(collector['stop_at_utc'])-
                         datetime.fromisoformat(collector['start_at_utc']),timedelta(seconds=180))
        self.assertFalse((Path(prepared['root'])/'daily_outer_check').exists())
        self.assertFalse((self.case/'unused.ecfg').exists())
