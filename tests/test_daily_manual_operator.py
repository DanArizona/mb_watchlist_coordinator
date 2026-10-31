"""Concrete manual operating composition; synthetic repositories and files only."""
from dataclasses import replace
from datetime import timedelta
from contextlib import redirect_stdout
import importlib.util
from io import StringIO
import json
import os
from pathlib import Path
from unittest.mock import patch
import unittest

import test_daily_operator as original
from mb_watchlist_coordinator import daily_operator as operator
from mb_watchlist_coordinator import daily_launch as launch
from mb_watchlist_coordinator.authenticated_startup import SessionPassword
from mb_watchlist_coordinator.daily_supervision import read_json,unseal,sealed,atomic_json
from mb_watchlist_coordinator.operating_plan import BROKER_MANUAL_PROFILE,proposed_policy
from mb_watchlist_coordinator.sampling_requests import digest
from mb_watchlist_coordinator.sampling_service import owner_lock


class ManualOperatorTests(unittest.TestCase):
    def setUp(self):
        self.old=original.OperatorTests('test_deployment_review_is_read_only_and_requires_exact_clean_baselines')
        self.old.setUp();self.addCleanup(self.old.doCleanups)
        self.case,self.source=self.old.case,self.old.source
        self.case.settings=replace(self.case.settings,policy_profile=BROKER_MANUAL_PROFILE,
            policy_sha256=digest(proposed_policy(BROKER_MANUAL_PROFILE)))
        self.policy=proposed_policy(BROKER_MANUAL_PROFILE)
        p=self.source/'RELEASE.json';release=json.loads(p.read_text())
        release.update(policy_profile=BROKER_MANUAL_PROFILE,policy_sha256=digest(self.policy),policy=self.policy)
        p.write_text(json.dumps(release))
        (self.source/'evidence').mkdir()
        checked={'contract':'manual-shared-broker-identity-offline-qualification-v1','result':'PASS','tests':71,'passed':71,
            'windows_checks_passed':True,'source_inventory_sha256':operator.MANUAL_BASE_INVENTORY,'failures':0,'errors':0,'skipped':0}
        (self.source/'evidence/WINDOWS_MANUAL_IDENTITY.json').write_text(json.dumps({'result':'ACCEPTED','windows_checks':checked}))
        self.old.inventory()

    def prepare(self,**kwargs):return self.old.prepare(**kwargs)

    def saved_driver(self):
        first=self.prepare();self.case.settings=replace(self.case.settings,state_root=first['state_root'])
        old=self.old.old;old.outer=Path(first['outer_root']);prior=old.review
        with patch.object(old,'review',side_effect=lambda **kw:prior(catalog=str(self.old.catalog),
                ecfg=str(self.case.root/'never-open.ecfg'),dependency_reader=lambda _:self.old.dependencies,
                policy_profile=BROKER_MANUAL_PROFILE,**kw)):
            driver=old.resumable()
        return first,driver

    def active_outer(self):
        first,driver=self.saved_driver();review,_=operator.load_review(self.source,first['review_path'])
        root=Path(first['outer_root']);binding=unseal(read_json(root/'operating-binding.json'))
        binding['public_launch']={'review':review,'approved_review_sha256':review['review_sha256'],
            'settings_approved_for_this_invocation':True}
        atomic_json(root/'operating-binding.json',sealed(binding));(root/'operating-result.json').unlink()
        atomic_json(root/'operating-live.json',sealed({'nonce':binding['nonce'],
            'configuration_sha256':binding['configuration_sha256'],'observed_at_utc':self.case.now.isoformat(),'phase':'ACTIVE'}))
        return first,driver

    def test_manual_preparation_adds_fixed_controls_feedback_and_resume_commands(self):
        first=self.prepare();folder=Path(first['review_path']).parent
        for name,command in (('MANUAL_CONTROLS','controls'),('MANUAL_STATUS','manual-status'),('PREPARE_RESUME','resume')):
            text=(folder/(name+'.cmd')).read_text()
            self.assertIn('"'+command+'"',text);self.assertIn('"'+first['review_path']+'"',text)
            self.assertNotIn('%*',text);self.assertNotIn('--activation-approved',text)
        self.assertTrue(first['manual_controls']['writes_require_active_controller'])
        self.assertFalse(first['manual_controls']['close_controls_stops_controller'])
        self.assertFalse(Path(first['state_root']).exists())

    def test_review_preserves_shared_policy_and_preopen_boundaries(self):
        first=self.prepare();review,_=operator.load_review(self.source,first['review_path'])
        self.assertEqual(first['policy'],self.policy)
        self.assertEqual(review['backend_review']['configuration']['collector']['max_symbols'],40)
        self.assertEqual(first['fresh_password_deadline_et'][11:16],'09:29')
        self.assertEqual(self.policy['limits']['maximum_identity_quote_calls'],120)

    def test_wrong_manual_evidence_or_policy_is_refused_even_after_rehash(self):
        evidence=self.source/'evidence/WINDOWS_MANUAL_IDENTITY.json';saved=evidence.read_text()
        bad=json.loads(saved);bad['windows_checks']['source_inventory_sha256']='0'*64;evidence.write_text(json.dumps(bad))
        self.old.inventory()
        with self.assertRaises(ValueError):self.prepare()
        evidence.write_text(saved)
        p=self.source/'RELEASE.json';value=json.loads(p.read_text());value['policy']['manual_controls']['actor_id']='different'
        p.write_text(json.dumps(value));self.old.inventory()
        with self.assertRaises(ValueError):self.prepare()

    def test_manual_qualification_requires_its_own_contract_inventory_and_cmd_proof(self):
        _,inventory,_=operator.release_info(self.source)
        marker={'contract':operator.MANUAL_QUALIFICATION,'result':'PASS','windows_checks_passed':True,
            'source_inventory_sha256':inventory,'tests':1,'passed':1,'failures':0,'errors':0,'skipped':0,
            'native_cmd_proof':{'result':'PASS'}}
        path=self.source/'runs/windows-qualification.json'
        for changed in ({'contract':'manual-shared-broker-identity-offline-qualification-v1'},
                {'source_inventory_sha256':'0'*64},{'native_cmd_proof':{'result':'FAILED'}},{'tests':0,'passed':0}):
            atomic_json(path,dict(marker,**changed))
            with self.assertRaises(ValueError):operator.windows_qualification(self.source,inventory)
        atomic_json(path,marker);self.assertEqual(operator.windows_qualification(self.source,inventory),marker)

    def test_manual_status_before_start_does_not_create_any_runtime_state(self):
        first=self.prepare();before=set(self.source.rglob('*'))
        with patch.object(SessionPassword,'prompt',side_effect=AssertionError('No prompt')):
            status=operator.manual_day_status(self.source,first['review_path'],clock=lambda:self.case.now)
        self.assertEqual(status['state'],'WAITING_FOR_CONTROLLER');self.assertIsNone(status['feedback'])
        self.assertFalse(status['writes_permitted']);self.assertEqual(before,set(self.source.rglob('*')))

    def test_controls_before_start_refuse_without_constructing_owner_or_prompt(self):
        first=self.prepare()
        with patch.object(SessionPassword,'prompt')as prompt,patch.object(launch,'DailyOperatingOwner')as owner:
            with self.assertRaises(ValueError):operator.open_day_controls(self.source,first['review_path'],
                qualification_reader=self.old.qualification,clock=lambda:self.case.now)
            prompt.assert_not_called();owner.assert_not_called()

    def test_active_exact_review_attaches_only_the_existing_controls_backend(self):
        first,_=self.active_outer();root=Path(first['outer_root']);canary=object()
        with owner_lock(root/'operating-owner.lock'),patch('mb_watchlist_coordinator.daily_manual_controls.open_daily_controls',return_value=canary)as opened:
            result=operator.open_day_controls(self.source,first['review_path'],qualification_reader=self.old.qualification,clock=lambda:self.case.now)
        self.assertIs(result,canary)
        opened.assert_called_once_with(first['state_root'],expected_configuration_sha256=json.loads(Path(first['review_path']).read_text())['configuration_sha256'],clock=unittest.mock.ANY)

    def test_owner_loss_and_stale_outer_refuse_before_opening_edit_backend(self):
        first,_=self.active_outer();root=Path(first['outer_root'])
        with patch('mb_watchlist_coordinator.daily_manual_controls.open_daily_controls')as opened:
            with self.assertRaises(ValueError):operator.open_day_controls(self.source,first['review_path'],qualification_reader=self.old.qualification,clock=lambda:self.case.now)
            with owner_lock(root/'operating-owner.lock'):
                with self.assertRaises(ValueError):operator.open_day_controls(self.source,first['review_path'],qualification_reader=self.old.qualification,clock=lambda:self.case.now+timedelta(seconds=4))
            opened.assert_not_called()

    def test_ended_outer_cannot_open_controls_for_a_resumed_controller(self):
        first,_=self.saved_driver()
        with patch('mb_watchlist_coordinator.daily_manual_controls.open_daily_controls')as opened:
            with self.assertRaisesRegex(ValueError,'ended'):operator.open_day_controls(self.source,first['review_path'],qualification_reader=self.old.qualification)
            opened.assert_not_called()

    def test_rehashed_other_review_cannot_attach_to_the_active_outer(self):
        first,_=self.active_outer();path=Path(first['review_path']);review=json.loads(path.read_text())
        review['approval_scope']='changed';review.pop('review_sha256');review['review_sha256']=digest(review);path.write_text(json.dumps(review))
        with owner_lock(Path(first['outer_root'])/'operating-owner.lock'),patch('mb_watchlist_coordinator.daily_manual_controls.open_daily_controls')as opened:
            with self.assertRaises(ValueError):operator.open_day_controls(self.source,path,qualification_reader=self.old.qualification,clock=lambda:self.case.now)
            opened.assert_not_called()

    def test_readonly_feedback_after_stop_retains_native_membership_without_restarting(self):
        first,_=self.saved_driver();self.case.now=self.case.at
        self.case.attach(create=False);mid=self.case.session.manual.submit('promote',symbol='IBM',target='hot')
        self.case.session.service.cycle();self.case.now+=timedelta(seconds=2);self.case.close()
        with patch.object(SessionPassword,'prompt')as prompt,patch.object(launch,'DailyOperatingOwner')as owner:
            status=operator.manual_day_status(self.source,first['review_path'],clock=lambda:self.case.now)
            prompt.assert_not_called();owner.assert_not_called()
        self.assertEqual(status['state'],'READ_ONLY_FEEDBACK');self.assertTrue(status['fresh'])
        self.assertFalse(status['writes_permitted']);self.assertEqual(status['feedback']['members']['hot'],['IBM'])
        self.assertEqual(status['feedback']['commands'][0]['command_id'],mid)

    def test_partial_or_corrupt_manual_state_is_unavailable_not_verified_empty(self):
        first,_=self.saved_driver();path=Path(first['state_root'])/'manual.sqlite3';path.write_bytes(b'corrupt')
        status=operator.manual_day_status(self.source,first['review_path'],clock=lambda:self.case.now)
        self.assertEqual(status['state'],'UNAVAILABLE');self.assertIsNone(status['feedback']);self.assertFalse(status['fresh'])

    def test_resume_commands_preserve_original_manual_configuration_and_budgets(self):
        first,driver=self.saved_driver()
        # The multi-symbol preflight correctly requires its original period
        # evidence, unlike the old single-symbol packaging fixture.
        from mb_watchlist_coordinator.daily_epoch_collector import make_daily_collector
        self.case.attach(create=False)
        config=launch.configuration(json.loads(Path(first['review_path']).read_text())['backend_review']['configuration'])
        def forbidden():raise AssertionError('Preparation cannot construct a provider')
        collector=make_daily_collector(config.collector,publication_session=self.case.session,
            client_factory=forbidden,clock=lambda:self.case.now,activation_approved=True)
        try:collector.prepare(create=True)
        finally:collector.close();self.case.close()
        before=driver.state.path.read_bytes();self.case.now=self.case.at
        resumed=operator.prepare_resume(self.source,first['review_path'],qualification_reader=self.old.qualification,
            dependency_reader=lambda _:self.old.dependencies,clock=lambda:self.case.now)
        value,_=operator.load_review(self.source,resumed['review_path'])
        self.assertEqual(value['configuration_sha256'],json.loads(Path(first['review_path']).read_text())['configuration_sha256'])
        self.assertEqual(value['resume']['charged_worker_starts'],1);self.assertEqual(value['resume']['minimum_replacement_hold_seconds'],15)
        self.assertFalse(value['resume']['budgets_reset']);self.assertEqual(driver.state.path.read_bytes(),before)
        self.assertTrue((Path(resumed['review_path']).parent/'MANUAL_CONTROLS.cmd').is_file())

    def test_rollback_routes_only_bound_hot_stop_and_preserves_manual_receipts(self):
        first,_=self.saved_driver();path=Path(first['state_root'])/'manual.sqlite3';before=path.read_bytes()
        result=operator.stop_day(self.source,first['review_path'])
        self.assertEqual(result['status'],'STOP_REQUESTED');self.assertFalse(result['processes_signaled'])
        self.assertEqual(result['unmanaged_channels_untouched'],['uni','focus','health']);self.assertEqual(path.read_bytes(),before)

    def test_existing_nonmanual_review_cannot_open_manual_feedback_or_controls(self):
        release=json.loads((self.source/'RELEASE.json').read_text());release.pop('policy_profile');release['policy_sha256']=digest(proposed_policy())
        (self.source/'RELEASE.json').write_text(json.dumps(release));self.old.inventory()
        first=self.prepare()
        for action in(operator.manual_day_status,operator.open_day_controls):
            with self.assertRaisesRegex(ValueError,'Manual controls require'):action(self.source,first['review_path'])

    def test_manual_start_requires_exact_approval_before_prompt_or_owner(self):
        first=self.prepare()
        with patch.object(SessionPassword,'prompt')as prompt,patch.object(launch,'DailyOperatingOwner')as owner:
            with self.assertRaises(ValueError):operator.start_day(self.source,first['review_path'],
                qualification_reader=self.old.qualification,clock=lambda:self.case.now)
            prompt.assert_not_called();owner.assert_not_called()

    def entry(self):
        path=Path(os.environ.get('MB_MANUAL_OPERATOR_ENTRY')or
            Path(__file__).resolve().parents[1]/'experiments/manual_operating_release_20261031/run.py')
        spec=importlib.util.spec_from_file_location('_manual_operator_delivery_test',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        module.ROOT=self.source
        return module

    def test_public_controls_entry_routes_existing_backend_to_original_window(self):
        entry=self.entry();backend=object();model=object()
        with patch.object(entry,'deny_network'),patch.object(operator,'open_day_controls',return_value=backend)as opened, \
                patch('mb_watchlist_coordinator.manual_membership.ManualMembershipModel',return_value=model), \
                patch('mb_watchlist_coordinator.manual_membership_window.ManualMembershipWindow')as window, \
                patch.object(SessionPassword,'prompt')as prompt,patch.object(launch,'DailyOperatingOwner')as owner:
            self.assertEqual(entry.main(['controls','--review','exact-review']),0)
            opened.assert_called_once_with(self.source,'exact-review');window.assert_called_once_with(model)
            window.return_value.run.assert_called_once();prompt.assert_not_called();owner.assert_not_called()

    def test_public_saved_feedback_entry_remains_non_gui_and_reports_unavailable(self):
        entry=self.entry()
        with patch.object(entry,'deny_network'),patch.object(operator,'manual_day_status',return_value={'state':'UNAVAILABLE'})as status, \
                patch('mb_watchlist_coordinator.manual_membership_window.ManualMembershipWindow')as window,redirect_stdout(StringIO()):
            self.assertEqual(entry.main(['manual-status','--review','exact-review']),1)
            status.assert_called_once_with(self.source,'exact-review');window.assert_not_called()
