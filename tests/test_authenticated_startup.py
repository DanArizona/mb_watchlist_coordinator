from contextlib import closing, redirect_stdout, redirect_stderr
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace, ModuleType
import unittest
from unittest.mock import patch

from mb_watchlist_coordinator.authenticated_startup import (AuthStartupSettings, SessionPassword,
    StartupError, receive_password, prepare_authenticated_client)

SECRET='SYNTHETIC-PASSWORD-CANARY-38'
URL='https://synthetic.invalid/callback?code=SYNTHETIC-CODE-CANARY-38'


class SecretHandoffTests(unittest.TestCase):
    def test_private_frame_is_bound_to_generation_and_repr_is_redacted(self):
        source=SessionPassword(SECRET,'a'*64)
        self.addCleanup(source.close)
        token='b'*32
        frame=source.frame(token)
        self.assertEqual(receive_password(io.BytesIO(frame),token),SECRET.encode())
        self.assertNotIn(SECRET,repr(source));self.assertNotIn(SECRET,json.dumps(source.identity))

    def test_wrong_generation_truncation_oversize_and_extra_fields_fail_closed(self):
        source=SessionPassword(SECRET,'a'*64);self.addCleanup(source.close)
        for frame,token in [(source.frame('b'*32),'c'*32),(b'{','b'*32),(b'x'*4097,'b'*32),
                (json.dumps({'contract':'anonymous-stdin-secret-v1','token':'b'*32,'password':SECRET,'extra':1}).encode(),'b'*32)]:
            with self.subTest(size=len(frame)):
                with self.assertRaises(StartupError) as result:receive_password(io.BytesIO(frame),token)
                self.assertEqual(result.exception.code,'secret_handoff_invalid')
                self.assertNotIn(SECRET,str(result.exception))

    def test_closed_controller_session_cannot_bootstrap_a_restart(self):
        source=SessionPassword(SECRET,'a'*64);source.close()
        with self.assertRaises(StartupError):source.frame('b'*32)

    def test_empty_invalid_or_overlarge_password_is_refused_without_echo(self):
        for password in ('','x'*513,b'\xff'):
            with self.assertRaises(StartupError):SessionPassword(password,'a'*64)

    def test_hidden_prompt_has_no_echo_fallback(self):
        import getpass
        with patch('getpass.getpass',side_effect=getpass.GetPassWarning('no terminal')):
            with self.assertRaises(StartupError):SessionPassword.prompt('a'*64)


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        self.now=datetime.now(timezone.utc);self.stop=self.now+timedelta(minutes=10)
        self.settings=AuthStartupSettings(str(self.root/'synthetic.ecfg'),self.stop.isoformat())
        self.created=[];self.status_calls=0;self.closed=[];self.auth=False;self.fail_load=False
        self.status_failure=None;self.after_construct=None;self.provider_failure=None;self.http=200;self.decode_failure=False

    def api(self):
        case=self
        def load(path,password):
            if case.fail_load:raise ValueError(SECRET+' '+URL)
            case.assertEqual(bytes(password),SECRET.encode())
            return object()
        def status(config,*,observed_at):
            case.status_calls+=1
            def require(at):
                case.assertEqual(at,case.stop+timedelta(minutes=75,seconds=30))
                if case.status_failure==case.status_calls:raise RuntimeError(SECRET)
            return SimpleNamespace(require_refresh_valid_through=require)
        def make(config,*,timeout,call_on_auth):
            case.assertEqual(timeout,3);case.created.append(call_on_auth)
            print(SECRET);print(URL,file=sys.stderr)
            if case.auth:call_on_auth(URL)
            if case.after_construct:case.after_construct()
            class Client:
                def quotes(self,symbols,*,fields):
                    print(SECRET)
                    if case.provider_failure:raise RuntimeError(case.provider_failure)
                    if case.auth:call_on_auth(URL)
                    class Response:
                        status_code=case.http;ok=case.http==200;text=SECRET
                        def json(self):
                            if case.decode_failure:raise ValueError(SECRET)
                            return {s:{'quote':{'lastPrice':1.0}} for s in symbols}
                    return Response()
                def close(self):case.closed.append(True)
            return Client()
        return SimpleNamespace(load_secure_schwab_config=load,read_schwab_token_status=status,
            make_client_from_config=make,DEFAULT_POLLING_REFRESH_MARGIN=timedelta(minutes=75,seconds=30))

    def start(self):return prepare_authenticated_client(self.settings,bytearray(SECRET.encode()),clock=lambda:self.now,secure_api=self.api())

    def test_initial_and_fresh_postconstruction_horizon_checks_and_suppressed_sdk_output(self):
        out,err=io.StringIO(),io.StringIO()
        with redirect_stdout(out),redirect_stderr(err):client=self.start();client.quotes(['MSFT'],fields='all');client.close()
        self.assertEqual(self.status_calls,2);self.assertEqual(out.getvalue()+err.getvalue(),'')
        self.assertEqual(self.closed,[True])

    def test_bad_configuration_error_is_redacted_before_client_creation(self):
        self.fail_load=True
        with self.assertRaises(StartupError) as e:self.start()
        self.assertNotIn(SECRET,str(e.exception));self.assertNotIn(URL,str(e.exception));self.assertFalse(self.created)

    def test_insufficient_horizon_blocks_before_constructor(self):
        self.status_failure=1
        with self.assertRaises(StartupError) as e:self.start()
        self.assertEqual(e.exception.code,'credential_horizon');self.assertFalse(self.created)

    def test_changed_postconstruction_horizon_closes_returned_client(self):
        self.status_failure=2
        with self.assertRaises(StartupError):self.start()
        self.assertEqual(self.closed,[True])

    def test_interactive_authorization_is_refused_and_client_closed(self):
        self.auth=True
        with self.assertRaises(StartupError) as e:self.start()
        self.assertEqual(e.exception.code,'authorization_required');self.assertEqual(self.closed,[True])

    def test_window_expiring_during_startup_closes_client(self):
        self.after_construct=lambda:setattr(self,'now',self.stop)
        with self.assertRaises(StartupError) as e:self.start()
        self.assertEqual(e.exception.code,'window_ended');self.assertEqual(self.closed,[True])

    def test_already_ended_window_does_not_read_configuration(self):
        self.now=self.stop
        with self.assertRaises(StartupError):self.start()
        self.assertFalse(self.created);self.assertEqual(self.status_calls,0)

    def test_http_authorization_failure_stops_future_provider_calls_and_hides_body(self):
        client=self.start();self.addCleanup(client.close);self.http=401
        response=client.quotes(['MSFT'],fields='all')
        self.assertNotIn(SECRET,response.text);self.assertEqual(response.json(),{})
        with self.assertRaises(StartupError):client.quotes(['MSFT'],fields='all')
        self.assertEqual(client.halt_reason,'authorization_required')

    def test_late_auth_callback_is_never_retried(self):
        client=self.start();self.addCleanup(client.close);self.auth=True
        client.quotes(['MSFT'],fields='all')
        with self.assertRaises(StartupError):client.quotes(['MSFT'],fields='all')

    def test_provider_exception_and_decode_error_are_redacted(self):
        client=self.start();self.addCleanup(client.close);self.provider_failure=SECRET+' '+URL
        with self.assertRaises(StartupError) as e:client.quotes(['MSFT'],fields='all')
        self.assertNotIn(SECRET,str(e.exception));self.assertNotIn(URL,str(e.exception))
        self.provider_failure=None;client=self.start();self.addCleanup(client.close);self.decode_failure=True
        with self.assertRaises(StartupError) as e:client.quotes(['MSFT'],fields='all').json()
        self.assertEqual(e.exception.code,'provider_decode_failed');self.assertNotIn(SECRET,str(e.exception))

    def test_explicit_timeout_and_absolute_path_are_required(self):
        for settings in (replace(self.settings,ecfg_path='relative.ecfg'),replace(self.settings,request_timeout_seconds=4),replace(self.settings,startup_timeout_seconds=20)):
            with self.assertRaises(ValueError):settings.payload()


class SharedCredentialInterfaceTests(unittest.TestCase):
    def test_actual_pinned_ecfg_status_and_client_factory_with_synthetic_sdk(self):
        from mb_tools.secure_config import save_ecfg
        from mb_tools.schwab_secure import DEFAULT_POLLING_REFRESH_MARGIN
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup);root=Path(temporary.name)
        now=datetime.now(timezone.utc);database=root/'synthetic-tokens.sqlite3'
        with closing(sqlite3.connect(database)) as connection,connection:
            connection.execute('CREATE TABLE schwabdev(access_token_issued TEXT,refresh_token_issued TEXT,expires_in INTEGER)')
            connection.execute('INSERT INTO schwabdev VALUES(?,?,?)',(now.isoformat(),now.isoformat(),1800))
        ecfg=root/'synthetic.ecfg';save_ecfg(ecfg,{'SCHWAB_APP_KEY':'A'*16,'SCHWAB_APP_SECRET':'B'*16,
            'SCHWAB_CALLBACK_URL':'https://synthetic.invalid','SCHWAB_TOKENS_DB':str(database),
            'SCHWAB_TOKEN_DB_FERNET_KEY':'synthetic-placeholder'},SECRET)
        captured={};sdk=ModuleType('schwabdev');sdk.__version__='4.0.0'
        class Client:
            def __init__(self,**kw):captured.update(kw)
            def close(self):captured['closed']=True
        sdk.Client=Client
        with patch.dict(sys.modules,schwabdev=sdk):
            client=prepare_authenticated_client(AuthStartupSettings(str(ecfg),(now+timedelta(minutes=5)).isoformat()),bytearray(SECRET.encode()))
            client.close()
        self.assertFalse(captured['open_browser_for_auth']);self.assertEqual(captured['timeout'],3)
        self.assertEqual(DEFAULT_POLLING_REFRESH_MARGIN,timedelta(minutes=75,seconds=30))
        self.assertTrue(captured['closed']);self.assertNotIn(SECRET,repr(client))
