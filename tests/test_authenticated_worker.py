from contextlib import closing
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest

from mb_tools.secure_config import save_ecfg
from mb_market_data.quote_observation_store import QuoteObservationStore
from mb_market_data.sampling_membership import SamplingHierarchyRevision
from mb_market_data.sampling_acquisition import MARKER
from mb_market_data.quote_journal_audit import audit_quote_journal
from mb_market_data.quote_journal_replay import QuoteJournalReplayReader
from mb_watchlist_coordinator.authenticated_startup import AuthStartupSettings, SessionPassword
from mb_watchlist_coordinator.authenticated_hot_worker import load_configuration
from mb_watchlist_coordinator.hot_recovery_collector import HotCollectorSettings, HotRecoveryCollector
from mb_watchlist_coordinator.recovery_workers import ManagedRecoveryWorker
from mb_watchlist_coordinator.sampling_requests import digest
from test_authenticated_startup import SECRET, URL


class AuthenticatedWorkerTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        self.at=(datetime.now(timezone.utc)+timedelta(days=1)).replace(hour=14,minute=0,second=0,microsecond=0)
        self.store=QuoteObservationStore(self.root/'quotes.sqlite3',session_date=self.at.date(),schema_version=2)
        self.store.initialize()
        self.store.record_membership_revision(SamplingHierarchyRevision(session_date=self.at.date(),revision=0,
            effective_at=self.at,uni_symbols=('MSFT',),focus_symbols=('MSFT',),hot_symbols=('MSFT',),
            source='synthetic-authenticated-startup',metadata={MARKER:True,'experimental':True}))
        self.binding={'journal':{'path':str(self.store.database_path.resolve()),'session_date':self.at.date().isoformat(),'schema_version':2},
            'contract':'synthetic-authenticated-publication'}
        self.settings=HotCollectorSettings(str(self.store.database_path),self.binding,self.at.isoformat(),
            (self.at+timedelta(seconds=60)).isoformat(),max_quote_calls=1,max_symbols=1)
        self.prepared=HotRecoveryCollector(self.settings,client_factory=lambda:None,clock=lambda:self.at)
        self.prepared.prepare(create=True)
        self.initial_runs=self.runs()
        self.database=self.root/'synthetic-token-metadata.sqlite3'
        with closing(sqlite3.connect(self.database)) as connection,connection:
            connection.execute('CREATE TABLE schwabdev(access_token_issued TEXT,refresh_token_issued TEXT,expires_in INTEGER)')
            connection.execute('INSERT INTO schwabdev VALUES(?,?,?)',(self.at.isoformat(),self.at.isoformat(),1800))
        self.ecfg=self.root/'synthetic.ecfg'
        save_ecfg(self.ecfg,{'SCHWAB_APP_KEY':'A'*16,'SCHWAB_APP_SECRET':'B'*16,
            'SCHWAB_CALLBACK_URL':'https://synthetic.invalid','SCHWAB_TOKENS_DB':str(self.database),
            'SCHWAB_TOKEN_DB_FERNET_KEY':'synthetic-placeholder'},SECRET)
        self.authentication=AuthStartupSettings(str(self.ecfg),self.settings.stop_at_utc,startup_timeout_seconds=4)
        self.config=self.root/'public-configuration.json'
        self.log=self.root/'synthetic-sdk.jsonl'
        self.simulation=self.root/'simulation.json'

    def runs(self):
        with closing(sqlite3.connect(self.store.database_path)) as connection:
            return connection.execute('SELECT count(*) FROM poll_run').fetchone()[0]

    def wait(self,predicate,seconds=9):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            result=predicate()
            if result:return result
            time.sleep(.03)
        self.fail('Authenticated process did not reach its bounded state')

    def events(self):return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def start(self,mode='normal',password=SECRET,crash_stage=None,timeout=4,wrong_context=False):
        self.authentication=replace(self.authentication,startup_timeout_seconds=timeout)
        self.config.write_text(json.dumps({'collector':asdict(self.settings),'authentication':asdict(self.authentication)}))
        self.real_start=datetime.now(timezone.utc)
        self.simulation.write_text(json.dumps({'mode':mode,'real_anchor_utc':self.real_start.isoformat(),
            'logical_anchor_utc':self.at.isoformat(),'log':str(self.log),'crash_stage':crash_stage}))
        context='0'*64 if wrong_context else digest(json.loads(self.config.read_text()))
        self.password=SessionPassword(password,context);self.addCleanup(self.password.close)
        self.managed=ManagedRecoveryWorker(self.root/'workers',role='experimental_hot',
            command=(sys.executable,'-I','-B',str(Path(__file__).parent/'fixtures/authenticated_worker_probe.py'),
                str(self.config),str(self.simulation)),binding=self.binding,startup_seconds=2,stale_seconds=3,
            startup_handoff=self.password)
        self.addCleanup(self.managed.stop_owned)
        return self.managed.ensure(start_allowed=True,resume_after_utc=self.at.isoformat())

    def finish(self):
        self.wait(lambda:self.managed.child.poll() is not None)
        code=self.managed.child.returncode
        self.managed.stop_owned()
        return code

    def auth_status(self):
        return json.loads((self.managed.root/(self.managed._job()['token']+'.auth.json')).read_text())['status']

    def no_plaintext_artifacts(self):
        for p in self.root.rglob('*'):
            if p.is_file():
                data=p.read_bytes()
                for secret in (SECRET,URL,'SYNTHETIC-CODE-CANARY-38'):
                    self.assertNotIn(secret.encode(),data,str(p.relative_to(self.root)))
        self.assertNotIn(SECRET,repr(self.managed.identity))
        self.assertNotIn(URL,repr(self.managed.last_exit))

    def test_real_entry_private_pipe_prepares_client_and_collects_native_quote(self):
        self.start();self.assertEqual(self.finish(),0)
        self.assertEqual(self.auth_status(),'credentials_accepted')
        self.assertEqual([e['event'] for e in self.events()],['constructed','quote','closed'])
        created=self.events()[0];self.assertEqual(created['timeout'],3);self.assertFalse(created['open_browser'])
        self.assertEqual(self.managed.last_exit['startup_handoff']['status'],'delivered')
        self.assertEqual(len(self.store.acquisitions_in_replay_order()),1)
        self.assertEqual(self.runs(),self.initial_runs+1)
        self.assertTrue(audit_quote_journal(self.store.database_path,audited_at=self.at+timedelta(seconds=2)).passed)
        def replay():return [(e.event_id,str(e)) for e in QuoteJournalReplayReader(self.store.database_path).events()]
        self.assertEqual(replay(),replay());self.no_plaintext_artifacts()

    def rejected(self,mode,expected,**kw):
        self.start(mode,**kw);self.assertEqual(self.finish(),70)
        self.assertEqual(self.auth_status(),expected)
        self.assertEqual(self.runs(),self.initial_runs)
        self.assertFalse(any(e['event']=='quote' for e in self.events()))
        self.no_plaintext_artifacts()

    def test_wrong_password_fails_before_native_run_registration(self):self.rejected('normal','startup_failed',password='synthetic-wrong-password')
    def test_interactive_auth_refusal_closes_client_and_registers_no_new_run(self):self.rejected('authorization','authorization_required')
    def test_constructor_error_does_not_retain_sdk_secrets(self):self.rejected('constructor_error','startup_failed')
    def test_changed_refresh_horizon_is_reread_before_registration(self):self.rejected('changed_horizon','credential_horizon')
    def test_window_expiring_inside_constructor_registers_no_new_run(self):self.rejected('window_expired','window_ended')

    def test_configuration_fence_rejects_a_different_public_configuration(self):
        self.start(wrong_context=True);self.assertEqual(self.finish(),70)
        self.assertEqual(self.runs(),self.initial_runs);self.assertFalse(self.events());self.no_plaintext_artifacts()

    def test_hung_constructor_has_child_enforced_deadline_without_controller_health_checks(self):
        self.start('hung_constructor',timeout=1)
        self.assertEqual(self.finish(),124)
        self.assertEqual(self.auth_status(),'startup_deadline_ended')
        self.assertEqual(self.runs(),self.initial_runs);self.no_plaintext_artifacts()

    def test_missing_private_stdin_frame_has_child_enforced_deadline(self):
        self.start(timeout=1)
        self.finish()
        # Same fenced job, no supervising parent and an open pipe with no EOF/data.
        child=subprocess.Popen([*self.managed.command,self.managed._job()['job_path']],stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        try:
            self.assertEqual(child.wait(timeout=4),124)
            output,error=child.communicate()
            self.assertEqual(output+error,b'')
            self.assertEqual(self.auth_status(),'startup_deadline_ended')
        finally:
            if child.poll() is None:child.kill()
            child.communicate()
        self.no_plaintext_artifacts()

    def test_same_manual_session_restarts_owned_child_and_recovers_saved_response_once(self):
        self.start(crash_stage='after_assembled');self.assertEqual(self.finish(),77)
        first=self.managed._job();self.assertEqual(len([e for e in self.events() if e['event']=='quote']),1)
        later=self.at+(datetime.now(timezone.utc)-self.real_start)
        def restart():
            result=self.managed.ensure(start_allowed=True,resume_after_utc=later.isoformat())
            return result if result.get('generation')==2 else None
        second=self.wait(restart)
        self.assertEqual(second['generation'],2);self.assertEqual(self.finish(),0)
        current=self.managed._job();self.assertNotEqual(current['token'],first['token'])
        self.assertEqual(current['identity'],first['identity'])
        self.assertEqual(len([e for e in self.events() if e['event']=='quote']),1)
        self.assertEqual(len(self.store.acquisitions_in_replay_order()),1)
        beat=json.loads(Path(current['heartbeat_path']).read_text());self.assertTrue(beat['recovery']['recovered'])
        self.assertEqual(beat['collector_status'],'budget_exhausted');self.no_plaintext_artifacts()

    def test_closed_manual_session_refuses_restart_without_recording_new_generation(self):
        self.start('authorization');self.finish();saved=self.managed.registry.read_bytes()
        self.password.close()
        def refusal():
            result=self.managed.ensure(start_allowed=True,resume_after_utc=self.at.isoformat())
            return result if result.get('reason')=='startup_credentials_unavailable' else None
        result=self.wait(refusal)
        self.assertEqual(result['reason'],'startup_credentials_unavailable')
        self.assertEqual(self.managed.registry.read_bytes(),saved);self.assertIsNone(self.managed.child)

    def test_closed_secret_does_not_stop_a_healthy_existing_owned_worker(self):
        self.start();self.wait(lambda:self.managed._heartbeat(self.managed._job()))
        child=self.managed.child;self.password.close()
        self.assertEqual(self.managed.ensure(start_allowed=True,resume_after_utc=self.at.isoformat())['status'],'RUNNING')
        self.assertIs(self.managed.child,child);self.assertIsNone(child.poll())

    def test_reopened_controller_cannot_restore_a_password_from_public_worker_files(self):
        self.start('authorization');self.finish();self.password.close()
        unavailable=SessionPassword('synthetic-unavailable',self.password.identity['configuration_sha256'])
        unavailable.close()
        reopened=ManagedRecoveryWorker(self.managed.root,role='experimental_hot',command=self.managed.command,
            binding=self.binding,startup_seconds=2,stale_seconds=3,startup_handoff=unavailable)
        saved=reopened.registry.read_bytes()
        def refusal():
            result=reopened.ensure(start_allowed=True,resume_after_utc=self.at.isoformat())
            return result if result.get('reason')=='startup_credentials_unavailable' else None
        self.wait(refusal)
        self.assertEqual(reopened.registry.read_bytes(),saved);self.assertIsNone(reopened.child)
        self.assertEqual(self.runs(),self.initial_runs);self.no_plaintext_artifacts()

    def test_http_authorization_failure_never_repeats_and_keeps_diagnostics_redacted(self):
        self.start('http_401');self.assertEqual(self.finish(),0)
        self.assertEqual(len([e for e in self.events() if e['event']=='quote']),1)
        beat=json.loads(Path(self.managed._job()['heartbeat_path']).read_text())
        self.assertEqual(beat['collector_status'],'blocked');self.no_plaintext_artifacts()

    def provider_refusal(self,mode):
        self.start(mode);self.assertEqual(self.finish(),0)
        self.assertEqual(len([e for e in self.events() if e['event']=='quote']),1)
        beat=json.loads(Path(self.managed._job()['heartbeat_path']).read_text())
        self.assertEqual(beat['collector_status'],'blocked');self.no_plaintext_artifacts()

    def test_late_authorization_callback_stops_after_one_native_attempt(self):self.provider_refusal('late_authorization')
    def test_provider_exception_cannot_leak_into_native_saved_evidence(self):self.provider_refusal('quote_error')
    def test_provider_decode_exception_cannot_leak_into_native_saved_evidence(self):self.provider_refusal('decode_error')

    def test_stop_during_constructor_closes_client_before_native_run_registration(self):
        self.start('stop_during_constructor');self.assertEqual(self.finish(),0)
        self.assertEqual(self.runs(),self.initial_runs)
        self.assertEqual([e['event'] for e in self.events()],['constructed','closed'])
        self.no_plaintext_artifacts()

    def test_strict_configuration_rejects_password_or_unknown_properties(self):
        value={'collector':asdict(self.settings),'authentication':asdict(self.authentication),'password':SECRET}
        self.config.write_text(json.dumps(value))
        with self.assertRaises(ValueError):load_configuration(self.config)


class DispatchGateRegressionTests(unittest.TestCase):
    def test_slow_lazy_client_cannot_dispatch_a_quote_after_original_gate_expires(self):
        from test_hot_recovery_collector import HotRecoveryCollectorTests
        fixture=HotRecoveryCollectorTests('runTest');fixture.setUp();self.addCleanup(fixture.doCleanups)
        def slow_factory():
            fixture.now=fixture.at+timedelta(seconds=3)
            return fixture.factory()
        reopened=HotRecoveryCollector(fixture.settings,client_factory=slow_factory,clock=lambda:fixture.now)
        reopened.prepare();fixture.advance(2)
        self.assertEqual(reopened.tick()['status'],'blocked');self.assertFalse(fixture.calls)

    def test_default_worker_identity_retains_the_accepted_v1_protocol(self):
        with tempfile.TemporaryDirectory() as folder:
            worker=ManagedRecoveryWorker(folder,role='experimental_hot',command=('synthetic-no-start',),binding={})
            self.assertEqual(worker.identity['contract'],'experimental-recovery-worker-v1')
            self.assertNotIn('startup_context',worker.identity)
