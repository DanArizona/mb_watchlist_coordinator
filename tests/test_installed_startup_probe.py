from contextlib import closing
from datetime import datetime,timedelta,timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from types import SimpleNamespace

from mb_tools.secure_config import save_ecfg
from mb_watchlist_coordinator.authenticated_startup import SessionPassword,StartupError
from mb_watchlist_coordinator.installed_startup_probe import (ProbeSettings,inspect_dependencies,
    run_probe,parse_receipt,source_hash,SOURCE_FILES)

SECRET='SYNTHETIC-PASSWORD-CANARY-40'
URL='https://synthetic.invalid/callback?code=SYNTHETIC-CODE-CANARY-40'


class InstalledDependencyTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)/'site-packages/mb_tools';self.root.mkdir(parents=True)
        self.expected={}
        for name in SOURCE_FILES:
            path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'# synthetic source\n')
            self.expected[name]=source_hash(path.read_bytes())
        self.versions={'mb-tools':'0.6.0','schwabdev':'4.0.0','cryptography':'46.0.0'}
    def inspect(self):return inspect_dependencies(self.expected,version_reader=self.versions.__getitem__,
        spec_finder=lambda _:SimpleNamespace(origin=str(self.root/'__init__.py')))
    def test_installed_metadata_and_all_reviewed_sources_are_recorded(self):
        result=self.inspect();self.assertTrue(result['qualified']);self.assertEqual(len(result['source']),8)
        self.assertEqual(result['versions'],self.versions)
    def test_windows_crlf_checkouts_have_same_canonical_source_hash(self):
        for name in SOURCE_FILES:(self.root/name).write_bytes(b'# synthetic source\r\n')
        result=self.inspect();self.assertTrue(result['qualified'])
        self.assertNotEqual(result['source']['__init__.py']['sha256'],result['source']['__init__.py']['canonical_source_sha256'])
    def test_changed_source_blocks_before_import_or_credentials(self):
        (self.root/'schwab_secure/client.py').write_bytes(b'# changed\n')
        self.assertEqual(self.inspect()['reason'],'dependency_source_mismatch')
    def test_unsupported_or_prerelease_sdk_blocks(self):
        for version in ('3.0.5','5.0.0','4.0.0rc1','4.0.0.dev1'):
            self.versions['schwabdev']=version
            self.assertEqual(self.inspect()['reason'],'sdk_version_unsupported')
    def test_missing_distribution_is_sanitized(self):
        def fail(_):raise ValueError(SECRET+' '+URL)
        result=inspect_dependencies(self.expected,version_reader=fail)
        self.assertEqual(result['reason'],'dependency_missing');self.assertNotIn(SECRET,json.dumps(result))
    def test_bundled_reference_cannot_be_misreported_as_installed(self):
        original=self.root;self.root=self.root.parent/'reference_mb_tools/src/mb_tools'
        self.assertEqual(self.inspect()['reason'],'dependency_reference_forbidden');self.root=original
    def test_incomplete_reviewed_source_inventory_is_refused(self):
        del self.expected['__init__.py'];self.assertFalse(self.inspect()['qualified'])


class InstalledProbeProcessTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup);self.root=Path(temporary.name)
        self.observed={'qualified':True,'reason':'probe_pass','execution':'synthetic_offline_fixture'}
        self.ecfg=self.root/'synthetic.ecfg';self.database=self.root/'metadata.sqlite3'
        now=datetime.now(timezone.utc)
        with closing(sqlite3.connect(self.database)) as connection,connection:
            connection.execute('CREATE TABLE schwabdev(access_token_issued TEXT,refresh_token_issued TEXT,expires_in INTEGER)')
            connection.execute('INSERT INTO schwabdev VALUES(?,?,?)',(now.isoformat(),now.isoformat(),1800))
        save_ecfg(self.ecfg,{'SCHWAB_APP_KEY':'A'*16,'SCHWAB_APP_SECRET':'B'*16,
            'SCHWAB_CALLBACK_URL':'https://synthetic.invalid','SCHWAB_TOKENS_DB':str(self.database),
            'SCHWAB_TOKEN_DB_FERNET_KEY':'synthetic-placeholder'},SECRET)
        self.outputs=self.root/'outputs';self.log=self.root/'sdk.jsonl';self.prompted=[];self.sources=[]
    def prompt(self,binding):
        self.prompted.append(True);source=SessionPassword(SECRET,binding);self.sources.append(source);return source
    def run_case(self,mode='normal',timeout=20,**kw):
        simulation=self.root/'simulation.json'
        simulation.write_text(json.dumps({'mode':mode,'inventory':self.observed,'log':str(self.log)}))
        command=(sys.executable,'-I','-B',str(Path(__file__).parent/'fixtures/installed_probe_worker.py'),str(simulation))
        path,report=run_probe(str(self.ecfg),self.outputs,{},command,inventory=lambda _:self.observed,
            prompt=kw.get('prompt',self.prompt),hard_seconds=timeout)
        self.assertEqual(json.loads(path.read_text()),report)
        for output in self.outputs.rglob('*'):
            if output.is_file():
                self.assertNotIn(SECRET.encode(),output.read_bytes());self.assertNotIn(URL.encode(),output.read_bytes())
        for source in self.sources:self.assertFalse(source._value)
        return report
    def events(self):return self.log.read_text().splitlines() if self.log.exists() else []
    def test_real_entry_uses_one_private_password_frame_and_one_quote_only(self):
        report=self.run_case();self.assertEqual(report['result'],'PASS');self.assertEqual(self.prompted,[True])
        self.assertEqual(self.events(),['constructed','quote','closed'])
        self.assertEqual(report['quote_dispatch_permits'],1);self.assertTrue(report['owned_child_exit_observed'])
        self.assertFalse(report['native_polling_started']);self.assertFalse(report['market_freshness_or_capacity_qualified'])
    def test_dependency_failure_saves_safe_diagnostics_without_prompt_or_child(self):
        self.observed={'qualified':False,'reason':'sdk_version_unsupported'}
        report=self.run_case();self.assertEqual(report['result'],'BLOCKED');self.assertFalse(self.prompted)
        self.assertEqual(report['reserved_quote_budget'],0);self.assertFalse(self.events())
    def test_human_prompt_failure_creates_no_provider_client(self):
        def fail(_):raise StartupError('credentials_unavailable')
        report=self.run_case(prompt=fail);self.assertEqual(report['reason'],'credentials_unavailable')
        self.assertFalse(self.events());self.assertEqual(report['reserved_quote_budget'],0)
    def test_insufficient_refresh_horizon_is_blocked_before_sdk_constructor(self):
        with closing(sqlite3.connect(self.database)) as connection,connection:
            connection.execute('UPDATE schwabdev SET refresh_token_issued=?',
                ((datetime.now(timezone.utc)-timedelta(days=7)+timedelta(minutes=10)).isoformat(),))
        report=self.run_case();self.assertEqual(report['reason'],'credential_horizon');self.assertFalse(self.events())
    def test_interactive_authorization_is_refused_without_quote(self):
        report=self.run_case('authorization');self.assertEqual(report['reason'],'authorization_required')
        self.assertEqual(self.events(),['constructed','closed']);self.assertEqual(report['quote_dispatch_permits'],0)
    def test_constructor_exception_is_redacted(self):
        report=self.run_case('constructor_error');self.assertEqual(report['reason'],'startup_failed')
        self.assertEqual(self.events(),['constructed'])
    def test_http_401_is_redacted_and_not_retried(self):
        report=self.run_case('http_error');self.assertEqual(report['reason'],'authorization_required')
        self.assertEqual(self.events().count('quote'),1);self.assertEqual(report['child_receipt']['http_status'],401)
    def test_late_auth_callback_is_refused_without_a_repeat_quote(self):
        report=self.run_case('late_authorization');self.assertEqual(report['reason'],'authorization_required')
        self.assertEqual(self.events().count('quote'),1)
    def test_transport_error_is_redacted_and_not_retried(self):
        report=self.run_case('transport_error');self.assertEqual(report['reason'],'provider_failed')
        self.assertEqual(self.events().count('quote'),1)
    def test_decode_error_is_redacted_and_not_retried(self):
        report=self.run_case('decode_error');self.assertEqual(report['reason'],'provider_decode_failed')
        self.assertEqual(self.events().count('quote'),1)
    def test_missing_symbol_fails_the_single_quote_proof(self):
        self.assertEqual(self.run_case('missing_symbol')['reason'],'provider_quote_invalid')
    def test_wrong_symbol_fails_the_single_quote_proof(self):
        self.assertEqual(self.run_case('wrong_symbol')['reason'],'provider_quote_invalid')
    def test_boolean_price_cannot_be_accepted_as_a_valid_quote(self):
        self.assertEqual(self.run_case('invalid_price')['reason'],'provider_quote_invalid')
    def test_hung_quote_is_terminated_by_exact_child_handle_without_retry(self):
        report=self.run_case('hung_quote',timeout=4)
        self.assertEqual(report['reason'],'probe_deadline_ended');self.assertTrue(report['owned_child_exit_observed'])
        self.assertIsNone(report['quote_dispatch_permits']);self.assertEqual(report['reserved_quote_budget'],1)
        self.assertEqual(self.events().count('quote'),1)
    def test_hung_constructor_is_stopped_with_unknown_dispatch_preserved(self):
        report=self.run_case('hung_constructor',timeout=12)
        self.assertEqual(report['reason'],'probe_deadline_ended');self.assertEqual(report['quote_dispatch_permits'],0)
        self.assertEqual(report['child_returncode'],124)
    def test_hung_close_cannot_be_misreported_as_success(self):
        report=self.run_case('hung_close',timeout=4)
        self.assertEqual(report['result'],'FAILED');self.assertEqual(report['reason'],'probe_deadline_ended')
    def test_arbitrary_child_output_is_rejected_without_echo_or_storage(self):
        report=self.run_case('raw_protocol_error');self.assertEqual(report['reason'],'child_protocol_invalid')
        self.assertIsNone(report['child_receipt'])
    def test_unreported_child_exit_does_not_claim_zero_quote_calls(self):
        report=self.run_case('early_exit');self.assertEqual(report['result'],'FAILED')
        self.assertIsNone(report['quote_dispatch_permits']);self.assertEqual(report['reserved_quote_budget'],1)


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        now=datetime.now(timezone.utc)
        self.settings=ProbeSettings(str(Path('/synthetic.ecfg').resolve()),'a'*32,now.isoformat(),
            (now+timedelta(seconds=20)).isoformat(),'b'*64)
        self.good={'contract':'installed-schwab-startup-probe-v1','nonce':'a'*32,'result':'PASS','reason':'probe_pass',
            'symbol':'SPY','quote_dispatch_permits':1,'quote_response_returned':True,'http_status':200,
            'returned_symbol_matches':True,'client_close_invoked':True,'dependency_sha256':'b'*64}
    def test_receipt_requires_exact_identity_and_quote_proof(self):
        self.assertEqual(parse_receipt(json.dumps(self.good).encode(),self.settings),self.good)
        for name,value in [('nonce','c'*32),('symbol','MSFT'),('quote_dispatch_permits',2),
                ('http_status',401),('returned_symbol_matches',False),('client_close_invoked',False),('secret',SECRET)]:
            changed=dict(self.good);changed[name]=value
            with self.assertRaises(StartupError):parse_receipt(json.dumps(changed).encode(),self.settings)
    def test_partial_oversized_or_duplicate_protocol_text_is_refused(self):
        for value in (b'{',b'x'*8193,(json.dumps(self.good)+'\n'+json.dumps(self.good)).encode()):
            with self.assertRaises(StartupError):parse_receipt(value,self.settings)
    def test_public_settings_cannot_increase_the_hard_window(self):
        from dataclasses import replace
        self.settings.payload()
        for candidate in (replace(self.settings,nonce='bad'),replace(self.settings,ecfg_path='relative.ecfg'),
                replace(self.settings,stop_at_utc=(datetime.fromisoformat(self.settings.started_at_utc)+timedelta(seconds=21)).isoformat())):
            with self.assertRaises(ValueError):candidate.payload()
