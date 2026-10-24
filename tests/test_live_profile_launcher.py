import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from live_profile_fixtures import config, INVENTORY
from mb_watchlist_coordinator.sampling_requests import digest

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('tested_live_launcher',ROOT/'experiments/live_profile_entry_20261024/launcher.py')
launcher=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(launcher)


class LauncherGateTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);self.root=Path(t.name)
        folder=self.root/'runs/verification/synthetic';folder.mkdir(parents=True)
        self.report=folder/'verification.json'
        self.report.write_text(json.dumps({'result':'PASS','tests':1,'failures':0,'errors':0}))
        self.marker={'inventory_sha256':'f'*64,'report':str(self.report),
            'report_sha256':hashlib.sha256(self.report.read_bytes()).hexdigest(),
            'executable':str(Path(sys.executable).resolve()),'python':list(sys.version_info[:3]),
            'platform':platform.platform()}
        self.path=self.root/'runs/OFFLINE_ACCEPTED.json';self.save()
    def save(self):self.path.write_text(json.dumps(self.marker))
    def gate(self):
        with patch.object(launcher,'sys',SimpleNamespace(platform='win32',executable=sys.executable,version_info=sys.version_info)):
            launcher.require_offline(self.root,'f'*64)
    def test_matching_current_host_and_source_report_is_required(self):self.gate()
    def test_inventory_python_or_report_change_invalidates_live_gate(self):
        for field,value in [('inventory_sha256','e'*64),('python',[3,11,0]),('report_sha256','0'*64)]:
            original=dict(self.marker);self.marker[field]=value;self.save()
            with self.assertRaises(ValueError):self.gate()
            self.marker=original
        self.save();self.report.write_text('{}')
        with self.assertRaises(ValueError):self.gate()
    def test_failed_verification_cannot_be_rehashed_into_acceptance(self):
        self.report.write_text(json.dumps({'result':'FAILED','tests':1,'failures':1,'errors':0}))
        self.marker['report_sha256']=hashlib.sha256(self.report.read_bytes()).hexdigest();self.save()
        with self.assertRaises(ValueError):self.gate()
    def test_live_role_is_blocked_before_any_credential_or_provider_function(self):
        with patch.object(launcher,'check_inventory',return_value='f'*64),patch.object(
                launcher,'require_offline',side_effect=ValueError('unqualified')),patch(
                'mb_watchlist_coordinator.live_profile.run_live',side_effect=AssertionError('No live call')):
            self.assertEqual(launcher.main(self.root,['ordinary','r0','r1','vault','--market-open-confirmed']),70)
    def test_stop_remains_available_without_an_offline_acceptance_marker(self):
        self.path.unlink()
        with patch.object(launcher,'check_inventory',return_value='f'*64),patch(
                'mb_watchlist_coordinator.live_profile.stop_live',return_value='Stop requested'),patch.object(
                launcher,'require_offline',side_effect=AssertionError('Stop must remain available')):
            self.assertEqual(launcher.main(self.root,['stop']),0)
    def test_failed_verifier_rerun_invalidates_an_earlier_acceptance_marker(self):
        report=self.root/'runs/verification/new/verification.json'
        class Child:
            def wait(self,timeout):
                report.parent.mkdir();report.write_text(json.dumps({'result':'FAILED','tests':1,'failures':1,'errors':0}));return 1
        with patch.object(launcher.subprocess,'Popen',return_value=Child()):
            self.assertEqual(launcher.offline(self.root,'f'*64),1)
        self.assertFalse(self.path.exists())
    def test_ordinary_and_recovery_launchers_select_exact_separate_profile_names(self):
        for mode,profile in [('ordinary','ordinary'),('recovery','owned_worker_recovery')]:
            with patch.object(launcher,'check_inventory',return_value='f'*64),patch.object(
                    launcher,'require_offline'),patch('mb_watchlist_coordinator.live_profile.run_live',
                    return_value=(self.root,{'outer':{'result':'READINESS_ONLY'}})) as run:
                self.assertEqual(launcher.main(self.root,[mode,'r0','r1','vault','--market-open-confirmed']),0)
                self.assertEqual(run.call_args.args[-1],profile)
                self.assertTrue(run.call_args.kwargs['market_open_confirmed'])
    def test_modified_module_cannot_execute_before_the_stdlib_source_guard(self):
        root=self.root/'synthetic_bundle';root.mkdir()
        launch=root/'launch.py';launch.write_bytes(Path(launcher.__file__).read_bytes())
        module=root/'coordinator/src/mb_watchlist_coordinator/live_profile.py';module.parent.mkdir(parents=True)
        module.write_text('pass\n')
        files={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
        (root/'SOURCE_INVENTORY.json').write_text(json.dumps({'files':files}))
        witness=self.root/'unexpected-module-execution'
        module.write_text('from pathlib import Path\nPath('+repr(str(witness))+').touch()\n')
        child=subprocess.run([sys.executable,'-I','-B',str(launch),'verify'],capture_output=True,timeout=5)
        self.assertEqual(child.returncode,70);self.assertFalse(witness.exists())


class PinnedRoleDispatchTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);self.root=Path(t.name)
        self.value,self.path,self.sha=config(self.root)
        import mb_watchlist_coordinator.live_profile_entry as entry
        self.entry=entry
    def call(self,role,extra=()):
        with patch.object(sys,'argv',['entry',role,str(self.path),self.sha,*extra]):return self.entry.main()
    def test_controller_and_reporter_are_ownership_gated_before_running(self):
        for role,fn in [('controller','run_controller'),('report','run_reporter')]:
            events=[]
            def gated(*a):events.append('gate')
            def run(*a):events.append(role);return 0
            with patch('mb_watchlist_coordinator.owned_process_scope.receive_gate',side_effect=gated),patch(
                    'mb_watchlist_coordinator.installed_startup_probe._silence'),patch(
                    'mb_watchlist_coordinator.live_profile.'+fn,side_effect=run):
                self.assertEqual(self.call(role),0)
            self.assertEqual(events,['gate',role])
    def test_worker_uses_existing_supervised_native_entry_and_bound_config(self):
        plan=SimpleNamespace(settings=SimpleNamespace(dependency_sha256=digest(INVENTORY)))
        auth=str(Path(self.value['settings']['experiment_root'])/'authenticated-worker.json')
        with patch('mb_watchlist_coordinator.live_profile.validate_configuration',return_value=plan),patch(
                'mb_watchlist_coordinator.installed_startup_probe.inspect_dependencies',return_value=INVENTORY),patch(
                'mb_watchlist_coordinator.supervised_hot_worker.run_supervised') as run:
            self.assertEqual(self.call('worker',(auth,'job.json')),0);run.assert_called_once_with(auth,'job.json')
    def test_changed_installed_dependencies_block_worker_before_authentication(self):
        plan=SimpleNamespace(settings=SimpleNamespace(dependency_sha256=digest(INVENTORY)))
        with patch('mb_watchlist_coordinator.live_profile.validate_configuration',return_value=plan),patch(
                'mb_watchlist_coordinator.installed_startup_probe.inspect_dependencies',return_value={'qualified':False}),patch(
                'mb_watchlist_coordinator.supervised_hot_worker.run_supervised',side_effect=AssertionError('No credential construction')):
            self.assertEqual(self.call('worker',('auth.json','job.json')),70)
