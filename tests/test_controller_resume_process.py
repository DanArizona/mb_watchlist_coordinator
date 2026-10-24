from contextlib import closing
from dataclasses import asdict
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from runtime_fixtures import RuntimeFixture,ScriptedFeed,SECRET
from mb_watchlist_coordinator.authenticated_startup import SessionPassword
from mb_watchlist_coordinator.controller_resume import ResumeSettings
from mb_watchlist_coordinator.resume_entry import parse_receipt
from mb_watchlist_coordinator.recovery_workers import next_future_slot
from mb_watchlist_coordinator.sampling_requests import digest,utc_text
from mb_watchlist_coordinator.sampling_service import owner_lock,ServiceBusy

PROBE=Path(__file__).parent/'fixtures/controller_resume_probe.py'
WORKER=Path(__file__).parent/'fixtures/supervised_hot_worker_probe.py'


class ManualResumeProcessTests(unittest.TestCase):
    def setUp(self):
        self.phase='first_native_acquisition'
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        # Create the original identity normally, never edit it in place.
        from mb_watchlist_coordinator.integrated_runtime import IntegratedRuntime
        self.f=RuntimeFixture(temp.name);self.addCleanup(self.f.session.close)
        self.simulation=self.f.root/'resume-simulation.json'
        self.worker_log=self.f.root/'worker-events.jsonl';self.controller_log=self.f.root/'controller-events.jsonl'
        command=(sys.executable,'-I','-B',str(WORKER),str(self.f.target/'authenticated-worker.json'),str(self.simulation))
        self.original=IntegratedRuntime(self.f.session,feed_client=ScriptedFeed(self.f.session.feed),worker_command=command)
        self.original.initialize();self.addCleanup(self.original.close)
        self.r=self.original
        self.original.worker.ensure=lambda **kw:{'status':'RUNNING','synthetic_worker':True}
        self.children=[];self.addCleanup(self.cleanup_children)

    def prepare(self,halt=False):
        self.f.now=self.f.start;self.original.step()
        if halt:
            from runtime_process_evidence import subsequent_halt_snapshot
            self.f.now+=timedelta(seconds=1)
            baseline=self.f.session.live.snapshot()['receipts'][0]['snapshot']
            self.f.session.live.record_snapshot(subsequent_halt_snapshot(baseline,observed_at=self.f.now,capture_id='process-resume-halt'))
            self.original.step()
        self.f.now=self.f.start+timedelta(seconds=4);self.original.close()
        self.f.realtime(at=self.f.now)

    def start(self,nonce='b'*32,**scenario):
        values={'mode':'normal','log':str(self.worker_log),'controller_log':str(self.controller_log),
            'real_anchor_utc':self.f.real.isoformat(),'logical_anchor_utc':self.f.logical.isoformat(),
            'debug_fixed_exceptions':True,**scenario}
        self.simulation.write_text(json.dumps(values))
        settings=ResumeSettings(str(self.f.target),self.f.session.plan.configuration_sha256,
            digest(self.original.identity),utc_text(self.f.clock()),nonce,self.original.command)
        path=self.f.root/('resume-'+nonce+'.json');path.write_text(json.dumps(asdict(settings)))
        sha=digest(settings.public())
        child=subprocess.Popen([sys.executable,'-I','-B',str(PROBE),str(path),sha,str(self.simulation)],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        secret=SessionPassword(SECRET,digest(json.loads((self.f.target/'authenticated-worker.json').read_text())))
        frame=secret.frame(nonce);secret.close()
        self.children.append(child)
        return child,frame,sha

    def run_child(self,nonce='b'*32,timeout=16,**scenario):
        child,frame,sha=self.start(nonce,**scenario)
        try:out,err=child.communicate(bytes(frame),timeout=timeout)
        finally:frame[:]=b'\0'*len(frame)
        self.assertNotIn(SECRET.encode(),out+err)
        self.assertNotIn(b'SYNTHETIC-RESUME-CODE-46',out+err)
        return child,out,err,sha

    def log(self,path):return [json.loads(s) for s in path.read_text().splitlines()] if path.exists() else []

    def ledger(self):
        with closing(sqlite3.connect(self.f.target/'resume.sqlite3')) as c:
            return [json.loads(row[0]) for row in c.execute('SELECT payload FROM resume_event ORDER BY sequence')]

    def native_count(self):return len(self.f.session.store.acquisitions_in_replay_order())

    def cleanup_children(self):
        for child in self.children:
            if child.poll() is None:
                child.terminate()
                try:child.wait(timeout=2)
                except subprocess.TimeoutExpired:child.kill();child.wait(timeout=2)
            for stream in (child.stdin,child.stdout,child.stderr):
                if stream is not None:stream.close()
        registry=self.f.target/'workers/worker.json'
        if registry.exists():
            job=json.loads(registry.read_text());Path(job['stop_path']).write_text(job['token'])
            until=time.monotonic()+5
            while time.monotonic()<until:
                try:
                    with owner_lock(Path(job['lease_path'])):break
                except ServiceBusy:time.sleep(.02)

    def no_secret(self):
        for p in self.f.root.rglob('*'):
            if p.is_file():
                self.assertNotIn(SECRET.encode(),p.read_bytes(),str(p))
                self.assertNotIn(b'SYNTHETIC-RESUME-CODE-46',p.read_bytes(),str(p))

    def hold_role(self,path):
        ready=self.f.root/'held-role-ready';release=self.f.root/'release-held-role'
        source="""from pathlib import Path
import sys,time,socket
sys.path.insert(0,sys.argv[1])
def denied(*a,**kw):raise RuntimeError('Network denied in synthetic role holder')
socket.socket.connect=socket.create_connection=socket.getaddrinfo=denied
from mb_watchlist_coordinator.sampling_service import owner_lock
with owner_lock(Path(sys.argv[2])):
 Path(sys.argv[3]).write_text('synthetic role held')
 deadline=time.monotonic()+6
 while not Path(sys.argv[4]).exists() and time.monotonic()<deadline:time.sleep(.01)
"""
        child=subprocess.Popen([sys.executable,'-I','-B','-c',source,str(Path(__file__).resolve().parents[1]/'src'),
            str(path),str(ready),str(release)],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        self.children.append(child);until=time.monotonic()+2
        while not ready.exists() and time.monotonic()<until:time.sleep(.01)
        self.assertTrue(ready.exists());return child,release

    def test_new_owned_process_reopens_with_private_credentials_and_no_new_parent_run(self):
        self.prepare();before=(self.f.target/'runtime-stop.json').read_bytes()
        child,out,err,sha=self.run_child()
        self.assertEqual(child.returncode,0,(out,err))
        self.assertEqual(parse_receipt(out,sha)['result'],'PASS')
        self.assertEqual((self.f.target/'runtime-stop.json').read_bytes(),before)
        self.assertEqual([x['kind'] for x in self.ledger()],['requested','authenticated','ready','stopped'])
        self.assertEqual(self.native_count(),0);self.no_secret()

    def test_reopened_process_starts_only_future_native_work_without_identity_refetch(self):
        self.prepare(halt=True);started=self.f.clock()
        child,out,err,sha=self.run_child(goal_native=1)
        self.assertEqual(child.returncode,0,(out,err));self.assertEqual(parse_receipt(out,sha)['result'],'PASS')
        quotes=[x for x in self.log(self.worker_log) if x['event']=='quote']
        self.assertGreaterEqual(len(quotes),1);self.assertTrue(all(q['symbols']==['NVDA'] for q in quotes))
        goal=next(x for x in self.log(self.controller_log) if x['event']=='native_goal')
        self.assertGreater(datetime.fromisoformat(goal['first_eligible_slot_utc']),started)
        self.assertFalse([x for x in self.log(self.controller_log) if x['event']=='identity_quote'])
        self.assertEqual(next(x for x in self.ledger() if x['kind']=='ready')['data']['counts']['identity_quote_permits'],1)
        self.no_secret()

    def test_controller_crash_leaves_a_charged_attempt_and_a_new_human_nonce_can_reopen(self):
        self.prepare()
        child,out,err,sha=self.run_child(controller_crash_stage='resume_reserved')
        self.assertEqual(child.returncode,77);self.assertFalse(out)
        self.assertEqual(self.ledger()[-1]['kind'],'requested')
        child,out,err,sha=self.run_child(nonce='c'*32)
        self.assertEqual(child.returncode,0,(out,err));self.assertEqual(parse_receipt(out,sha)['result'],'PASS')
        self.assertIn('abandoned',[x['kind'] for x in self.ledger()]);self.no_secret()

    def test_controller_crash_after_runtime_binding_keeps_the_original_window_and_ledgers(self):
        self.prepare();binding=(self.f.target/'runtime-binding.json').read_bytes()
        child,out,err,sha=self.run_child(controller_crash_stage='runtime_reopened')
        self.assertEqual(child.returncode,77)
        child,out,err,sha=self.run_child(nonce='c'*32)
        self.assertEqual(child.returncode,0,(out,err));self.assertEqual(parse_receipt(out,sha)['result'],'PASS')
        self.assertEqual((self.f.target/'runtime-binding.json').read_bytes(),binding)
        self.no_secret()

    def test_orphaned_native_generation_is_token_fenced_and_next_generation_uses_remaining_budget(self):
        self.prepare(halt=True)
        child,out,err,sha=self.run_child(goal_native=1,crash_after_native_goal=True)
        self.assertEqual(child.returncode,78);self.assertFalse(out)
        old=json.loads((self.f.target/'workers/worker.json').read_text())
        before=self.native_count()
        child,out,err,sha=self.run_child(nonce='c'*32,goal_native=before+1,minimum_generation=2)
        self.assertEqual(child.returncode,0,(out,err));self.assertEqual(parse_receipt(out,sha)['result'],'PASS')
        new=json.loads((self.f.target/'workers/worker.json').read_text())
        self.assertEqual((old['generation'],new['generation']),(1,2));self.assertNotEqual(old['token'],new['token'])
        self.assertTrue(Path(old['stop_path']).exists())
        ready=[x for x in self.ledger() if x['kind']=='ready']
        self.assertEqual(ready[-1]['data']['counts']['identity_quote_permits'],1)
        self.assertEqual(ready[-1]['data']['counts']['selected_symbol'],'NVDA')
        self.assertGreaterEqual(ready[-1]['data']['counts']['hot_quote_permits'],1)
        self.assertEqual(new['identity'],old['identity']);self.no_secret()

    def test_eight_second_credential_watchdog_preempts_a_blocked_synthetic_sdk(self):
        self.prepare();began=time.monotonic()
        child,out,err,sha=self.run_child(resume_mode='slow_credential',timeout=12)
        self.assertEqual(child.returncode,124,(out,err));self.assertLess(time.monotonic()-began,10)
        self.assertEqual(parse_receipt(out,sha)['reason'],'credential_deadline_ended')
        self.assertFalse((self.f.target/'workers/worker.json').exists());self.no_secret()

    def test_independent_preparation_deadline_does_not_wait_for_the_blocked_driver(self):
        self.prepare();began=time.monotonic()
        child,out,err,sha=self.run_child(controller_hang_stage='credentials_accepted',hard_seconds=1,timeout=5)
        self.assertEqual(child.returncode,124,(out,err));self.assertLess(time.monotonic()-began,4)
        self.assertEqual(parse_receipt(out,sha)['reason'],'preparation_deadline_ended')
        self.no_secret()

    def test_sdk_authorization_and_arbitrary_exceptions_are_redacted_without_dispatch(self):
        self.prepare()
        for nonce,mode in (('b'*32,'authorization'),('c'*32,'constructor_error')):
            child,out,err,sha=self.run_child(nonce=nonce,resume_mode=mode)
            self.assertEqual(child.returncode,70,(out,err));self.assertEqual(parse_receipt(out,sha)['result'],'FAILED')
        self.assertFalse((self.f.target/'workers/worker.json').exists());self.no_secret()

    def test_three_total_worker_generations_remain_exhausted_across_human_controller_reopens(self):
        self.prepare(halt=True)
        for n,nonce in enumerate(('b'*32,'c'*32,'d'*32),1):
            child,out,err,sha=self.run_child(nonce=nonce,goal_native=n,minimum_generation=n)
            self.assertEqual(child.returncode,0,(out,err));self.assertEqual(parse_receipt(out,sha)['result'],'PASS')
            self.assertEqual(json.loads((self.f.target/'workers/worker.json').read_text())['generation'],n)
        before=len([x for x in self.log(self.controller_log) if x['event']=='resume_client_constructed'])
        child,out,err,sha=self.run_child(nonce='e'*32)
        self.assertEqual(child.returncode,70,(out,err))
        self.assertEqual(parse_receipt(out,sha)['reason'],'budget_exhausted')
        self.assertEqual(len([x for x in self.log(self.controller_log) if x['event']=='resume_client_constructed']),before)

    def test_saved_native_response_survives_worker_and_controller_exit_without_quote_refetch(self):
        self.prepare(halt=True)
        child,out,err,sha=self.run_child(goal_native=1,crash_stage='after_assembled',crash_after_worker_exit=True)
        self.assertEqual(child.returncode,79,(out,err));self.assertFalse(out)
        self.assertEqual(self.native_count(),0)
        calls=len([x for x in self.log(self.worker_log) if x['event']=='quote'])
        self.assertEqual(calls,1)
        child,out,err,sha=self.run_child(nonce='c'*32)
        self.assertEqual(child.returncode,0,(out,err));self.assertEqual(parse_receipt(out,sha)['result'],'PASS')
        self.assertEqual(self.native_count(),1)
        self.assertEqual(len([x for x in self.log(self.worker_log) if x['event']=='quote']),calls)
        ready=[x for x in self.ledger() if x['kind']=='ready'][-1]
        self.assertTrue(ready['data']['native_recovery']['recovered'])
        self.assertEqual(ready['data']['counts']['hot_quote_permits'],1)
        self.assertEqual(ready['data']['counts']['worker_starts'],1)

    def test_busy_unowned_hot_role_blocks_reopen_without_stopping_that_process(self):
        self.prepare();holder,release=self.hold_role(self.f.target/'workers/worker.lock')
        child,out,err,sha=self.run_child(hard_seconds=1,timeout=5)
        self.assertEqual(child.returncode,124,(out,err))
        self.assertEqual(parse_receipt(out,sha)['reason'],'preparation_deadline_ended')
        self.assertIsNone(holder.poll());self.assertFalse((self.f.target/'workers/worker.json').exists())
        release.write_text('release synthetic holder');holder.wait(timeout=2)

    def test_pending_feed_is_not_completed_or_replaced_until_its_network_lease_is_free(self):
        self.prepare();self.f.realtime(at=self.f.start+timedelta(seconds=65))
        reservation=self.f.session.feed.reserve(synthetic=True);self.assertIsNotNone(reservation)
        holder,release=self.hold_role(self.f.target/'feed.network.lock')
        observed=[]
        def release_after_authentication():
            until=time.monotonic()+4
            while time.monotonic()<until:
                rows=self.log(self.controller_log)
                if any(x.get('stage')=='credentials_accepted' for x in rows):
                    observed.append(self.f.session.feed.snapshot()['pending']['attempt_id'])
                    time.sleep(.1);release.write_text('release synthetic network holder');return
                time.sleep(.02)
            release.write_text('release after bounded observer timeout')
        thread=threading.Thread(target=release_after_authentication);thread.start();self.addCleanup(thread.join)
        child,out,err,sha=self.run_child()
        self.assertEqual(child.returncode,0,(out,err));self.assertEqual(parse_receipt(out,sha)['result'],'PASS')
        holder.wait(timeout=2);self.assertEqual(observed,[reservation['attempt_id']])
        feed=self.f.session.feed.snapshot()
        self.assertIsNone(feed['pending']);self.assertEqual(len(feed['attempts']),2)
        self.assertEqual(feed['attempts'][-1]['outcome']['kind'],'unknown_interrupted')
