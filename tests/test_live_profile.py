from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from live_profile_fixtures import config, FakeAPI, SECRET, INVENTORY
from test_integrated_catalog import catalog
from mb_watchlist_coordinator.authenticated_startup import SessionPassword
from mb_watchlist_coordinator.live_profile import (source_guard, validate_configuration,
    worker_command, request_stop, stop_request, run_controller, run_reporter, run_live)
from mb_watchlist_coordinator.sampling_requests import digest, timestamp
from mb_watchlist_coordinator.sampling_service import owner_lock, ServiceBusy


class EntryBindingTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);self.root=Path(t.name)
        self.value,self.path,self.sha=config(self.root)
        self.verify=lambda *a:None
    def validate(self, value=None, sha=None):
        return validate_configuration(value or self.value,sha or self.sha,verify_source=self.verify)
    def test_exact_original_plan_and_entry_command_bind_all_three_worker_arguments(self):
        plan=self.validate();command=worker_command(self.value,self.path,self.sha)
        self.assertEqual(command[-4:],('worker',str(self.path),self.sha,str(Path(plan.settings.experiment_root)/'authenticated-worker.json')))
        self.assertEqual((timestamp(plan.public['stop_at_utc'])-timestamp(plan.public['start_at_utc'])).total_seconds(),720)
        self.assertEqual(plan.public['maximum_hot_quote_permits'],60)
        self.assertEqual(plan.public['maximum_identity_quote_permits'],3)
    def test_mutated_configuration_or_unknown_driver_field_is_rejected(self):
        for field,value in [('nonce','b'*32),('preflight_sha256','a'*64),('entry_path','unreviewed.py'),('sdk','synthetic')]:
            with self.subTest(field=field):
                changed=dict(self.value);changed[field]=value
                with self.assertRaises(ValueError):self.validate(changed,digest(changed))
    def test_source_change_after_parent_validation_is_not_adopted(self):
        def reject(*a):raise ValueError('changed source')
        with self.assertRaises(ValueError):validate_configuration(self.value,self.sha,verify_source=reject)
    def test_stop_is_idempotent_and_retains_the_first_bound_reason(self):
        first=request_stop(self.value,self.sha,'native_budget_exhausted')
        self.assertEqual(request_stop(self.value,self.sha),first)
        self.assertEqual(stop_request(self.value,self.sha),first)
    def test_foreign_nonce_or_unknown_stop_reason_is_rejected(self):
        request_stop(self.value,self.sha)
        p=self.root/'STOP_REQUEST.json';raw=json.loads(p.read_text());raw['nonce']='b'*32;p.write_text(json.dumps(raw))
        with self.assertRaises(ValueError):stop_request(self.value,self.sha)
        with self.assertRaises(ValueError):request_stop(self.value,self.sha,'restart_production')
    def test_reporter_failure_is_explicit_read_only_and_bound(self):
        outer=Path(self.value['outer_root']);outer.mkdir()
        with patch('mb_watchlist_coordinator.profile_report.report_saved_profile',side_effect=ValueError(SECRET)),patch(
                'mb_watchlist_coordinator.authenticated_startup.prepare_authenticated_client',side_effect=AssertionError('No report credentials')):
            self.assertEqual(run_reporter(self.value,self.sha,verify_source=self.verify),0)
        report=json.loads((outer/'native-profile-report.json').read_text())
        self.assertEqual(report['result'],'FAILED');self.assertTrue(report['reporting_read_only'])
        self.assertFalse(report['credential_access']);self.assertNotIn(SECRET,json.dumps(report))


class SourceGuardTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);self.root=Path(t.name)
        p=self.root/'entry.py';p.write_text('print(1)\n')
        (self.root/'SOURCE_INVENTORY.json').write_text(json.dumps({'files':{'entry.py':hashlib.sha256(p.read_bytes()).hexdigest()}}))
    def test_runs_are_mutable_but_source_inventory_hash_is_bound(self):
        sha=source_guard(self.root);(self.root/'runs').mkdir();(self.root/'runs/status.json').write_text('{}')
        self.assertEqual(source_guard(self.root,sha),sha)
        with self.assertRaises(ValueError):source_guard(self.root,'0'*64)
    def test_changed_extra_source_and_extra_bytecode_fail_closed(self):
        for name in ('extra.py','extra.pyc'):
            p=self.root/name;p.write_text('extra')
            with self.assertRaises(ValueError):source_guard(self.root)
            p.unlink()
        (self.root/'entry.py').write_text('changed')
        with self.assertRaises(ValueError):source_guard(self.root)


class ControllerTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);self.root=Path(t.name)
        self.value,self.path,self.sha=config(self.root);Path(self.value['outer_root']).mkdir()
        self.now=timestamp(self.value['settings']['password_submitted_at_utc'])
        self.events=[];self.stages=[]
    def run_controller(self,mode='normal', **kw):
        secret=SessionPassword(SECRET,self.sha);frame=secret.frame(self.value['nonce']);secret.close()
        def stage(name):
            self.stages.append(name)
            if name=='runtime_ready':(Path(self.value['outer_root'])/'STOP.json').write_text('{}')
        args=dict(clock=lambda:self.now, inventory=lambda _:INVENTORY,
            secure_api=FakeAPI(self.value['settings']['experiment_root'],self.events,mode=mode),
            catalog_acquirer=lambda **kw:catalog(self.now),verify_source=lambda *a:None,on_stage=stage)
        args.update(kw)
        # This unit suite checks controller/bootstrap ordering without launching
        # a worker. The affected process suite exercises real preparation.
        with patch('mb_watchlist_coordinator.integrated_runtime.IntegratedRuntime.prepare_worker'):
            return run_controller(self.value,self.path,self.sha,io.BytesIO(frame),**args)
    def scan(self):
        from saved_artifact_scan import scan_saved_artifacts
        scan_saved_artifacts(self.root,(SECRET.encode(),))
    def test_real_bootstrap_runtime_and_profile_order_then_owned_close_without_dispatch(self):
        self.assertEqual(self.run_controller(),0)
        self.assertLess(self.stages.index('credentials_accepted'),self.stages.index('directory_invocation_reserved'))
        self.assertLess(self.stages.index('directory_captured'),self.stages.index('initial_poll_run_registered'))
        self.assertLess(self.stages.index('initial_poll_run_registered'),self.stages.index('runtime_ready'))
        self.assertEqual(self.events,['load','construct','close']);self.scan()
    def test_wrong_credentials_or_authorization_create_no_native_state_and_redact(self):
        for mode in ('load_error','authorization'):
            with self.subTest(mode=mode):
                self.assertEqual(self.run_controller(mode),70)
                self.assertFalse(Path(self.value['settings']['experiment_root']).exists());self.scan()
    def test_catalog_failure_preserves_reservation_without_starting_native_poll_run(self):
        from mb_watchlist_coordinator.integrated_catalog import CatalogError
        def fail(**kw):raise CatalogError('catalog_http_or_timing_invalid')
        self.assertEqual(self.run_controller(catalog_acquirer=fail),70)
        root=Path(self.value['settings']['experiment_root'])
        self.assertTrue((root/'directory.sqlite3').is_file());self.assertFalse((root/'quotes.sqlite3').exists());self.scan()
    def test_unknown_source_or_expired_preparation_cannot_reach_authentication(self):
        self.now+=timedelta(seconds=61)
        self.assertEqual(self.run_controller(),70);self.assertEqual(self.events,[]);self.scan()
    def test_credential_deadline_cannot_be_increased_by_a_driver(self):
        self.assertEqual(self.run_controller(credential_seconds=9),70)
        self.assertEqual(self.events,[])
    def test_recovery_profile_is_bound_without_an_unearned_fault_or_restart(self):
        self.value,self.path,self.sha=config(self.root,'owned_worker_recovery')
        self.assertEqual(self.run_controller(),0)
        state=json.loads((Path(self.value['settings']['experiment_root'])/'profile.json').read_text())
        self.assertEqual(state['binding']['profile'],'owned_worker_recovery')
        self.assertEqual([e['kind'] for e in state['events']],['stop'])


class OperatorParentTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);self.root=Path(t.name)
        value,self.path,self.sha=config(self.root)
        self.opening=value['settings']['opening_proposal'];self.focus=value['settings']['focus_proposal']
        self.ecfg=value['settings']['ecfg_path']
        # Fixed synthetic weekday. No public exchange-calendar/network claim.
        self.at=datetime(2026,10,26,14,0,0,tzinfo=timezone.utc)
        from mb_market_data.sampling_membership import SamplingHierarchyRevision
        for name in (self.opening,self.focus):
            p=Path(name);raw=json.loads(p.read_text());raw['session_date']='2026-10-26';raw['effective_at']='2026-10-26T09:30:00-04:00';p.write_text(json.dumps(raw))
    def invoke(self,**kw):
        args=dict(market_open_confirmed=True,clock=lambda:self.at,inventory=lambda _:INVENTORY,
            prompt=lambda sha:SessionPassword(SECRET,sha),progress=lambda *a,**kw:None)
        args.update(kw)
        with patch('mb_watchlist_coordinator.live_profile.source_guard',return_value='e'*64):
            return run_live(self.root,self.opening,self.focus,self.ecfg,'ordinary',**args)
    def test_no_market_confirmation_or_dependency_mismatch_prompts_or_launches(self):
        def forbidden(*a):raise AssertionError('No password prompt allowed')
        for kwargs in ({'market_open_confirmed':False},{'inventory':lambda _:{'qualified':False}}):
            with self.assertRaises(ValueError):self.invoke(prompt=forbidden,**kwargs)
    def test_mutated_proposal_while_prompting_cannot_reach_a_controller(self):
        def prompt(sha):
            p=Path(self.opening);p.write_text(p.read_text()+'\n');return SessionPassword(SECRET,sha)
        with self.assertRaises(ValueError):self.invoke(prompt=prompt)
    def test_second_experiment_cannot_bypass_the_parent_lifetime_lease(self):
        runs=self.root/'runs';runs.mkdir()
        with owner_lock(runs/'live-profile.owner.lock'):
            with self.assertRaises(ServiceBusy):self.invoke(prompt=lambda _:self.fail('Unexpected prompt'))
    def test_unconfirmed_previous_scope_blocks_a_new_prompt_and_budget(self):
        from mb_watchlist_coordinator.live_profile import CONTRACT
        runs=self.root/'runs';folder=runs/'previous';folder.mkdir(parents=True)
        pointer={'contract':CONTRACT,'phase':'ACTIVE','launch_path':str(folder/'launch.json'),'launch_sha256':'a'*64}
        (runs/'active_live_profile.json').write_text(json.dumps(pointer))
        for phase in ('ACTIVE','CLOSED'):
            pointer['phase']=phase;(runs/'active_live_profile.json').write_text(json.dumps(pointer))
            (folder/'summary.json').write_text(json.dumps({'outer':{'cleanup':{'status':'CLEANUP_INCOMPLETE'},'reporter_cleanup':None}}))
            with self.assertRaises(ValueError):self.invoke(prompt=lambda _:self.fail('Unexpected prompt'))
    def test_parent_wires_private_frame_two_fixed_roles_and_original_frozen_bounds(self):
        case=self;frames=[]
        class Harness:
            def __init__(self,root,schedule,nonce,**kw):
                self.root=root;root.mkdir();case.assertEqual(schedule.validate()[2]-schedule.validate()[1],timedelta(seconds=720))
            def run(self,command,**kw):
                frames.append(kw['credential_frame']);case.assertIn(SECRET.encode(),frames[-1])
                case.assertEqual(command[-3],'controller');case.assertEqual(kw['reporter_command'][-3],'report')
                case.assertNotIn(SECRET,' '.join(command));return {'result':'INCOMPLETE','stop_reason':'operator_stop'}
        folder,summary=self.invoke(harness_factory=Harness)
        self.assertEqual(summary['maximum_quote_permits'],63)
        self.assertTrue(all(b==0 for b in frames[0]))
        self.assertEqual(json.loads((self.root/'runs/active_live_profile.json').read_text())['phase'],'CLOSED')
        from saved_artifact_scan import scan_saved_artifacts
        scan_saved_artifacts(folder,(SECRET.encode(),))
    def test_failed_parent_setup_closes_the_pointer_and_redacts_saved_failure(self):
        def fail(*a,**kw):raise RuntimeError(SECRET)
        with self.assertRaises(RuntimeError):self.invoke(harness_factory=fail)
        self.assertEqual(json.loads((self.root/'runs/active_live_profile.json').read_text())['phase'],'CLOSED')
        from saved_artifact_scan import scan_saved_artifacts
        scan_saved_artifacts(self.root/'runs',(SECRET.encode(),))
