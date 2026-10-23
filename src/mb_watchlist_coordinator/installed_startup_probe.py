"""One human-started installed-client probe; no poller or automatic retry."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
from importlib import metadata, util
import json
import logging
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import uuid

from .authenticated_startup import (AuthStartupSettings, SessionPassword, StartupError,
    prepare_authenticated_client, receive_password, CODES)
from .sampling_requests import canonical, digest, timestamp
from .recovery_workers import atomic_json

CONTRACT='installed-schwab-startup-probe-v1'
SYMBOL='SPY'
HARD_SECONDS=20
MAX_REPORT_BYTES=8192
REASONS=CODES|frozenset(('dependency_missing','dependency_source_mismatch',
    'dependency_reference_forbidden','sdk_version_unsupported','configuration_invalid',
    'probe_deadline_ended','child_protocol_invalid','operator_interrupted',
    'provider_quote_invalid','probe_pass'))
SOURCE_FILES=('__init__.py','schwab_secure/__init__.py','schwab_secure/client.py',
    'schwab_secure/config.py','schwab_secure/status.py','schwab_secure/reauthorize.py',
    'secure_config/__init__.py','secure_config/ecfg.py')


def source_hash(data):
    """Only normalize Git's Windows CRLF checkout conversion."""
    return hashlib.sha256(data.replace(b'\r\n',b'\n')).hexdigest()


def inspect_dependencies(expected, *, version_reader=metadata.version, spec_finder=util.find_spec):
    result={'qualified':False,'reason':'dependency_missing','python':list(sys.version_info[:3]),
        'executable':str(Path(sys.executable).resolve()),'versions':{},'mb_tools_root':None,'source':{}}
    try:
        if set(expected)!=set(SOURCE_FILES) or any(not re.fullmatch('[0-9a-f]{64}',v) for v in expected.values()):
            raise ValueError()
        for package in ('mb-tools','schwabdev','cryptography'):
            result['versions'][package]=version_reader(package)
        sdk=result['versions']['schwabdev']
        if not isinstance(sdk,str) or not re.fullmatch(r'4\.\d+\.\d+(?:\.post\d+)?',sdk):
            result['reason']='sdk_version_unsupported';return result
        spec=spec_finder('mb_tools')
        root=Path(spec.origin).resolve().parent
        result['mb_tools_root']=str(root)
        if any(p.name=='reference_mb_tools' for p in root.parents):
            result['reason']='dependency_reference_forbidden';return result
        for name in SOURCE_FILES:
            raw=(root/name).read_bytes()
            result['source'][name]={'sha256':hashlib.sha256(raw).hexdigest(),
                'canonical_source_sha256':source_hash(raw),'expected_sha256':expected[name]}
        if any(v['canonical_source_sha256']!=v['expected_sha256'] for v in result['source'].values()):
            result['reason']='dependency_source_mismatch';return result
        result.update(qualified=True,reason='probe_pass')
    except Exception:
        # No arbitrary import/metadata/OS exception can enter a retained report.
        result.update(qualified=False,reason='dependency_missing')
    return result


@dataclass(frozen=True)
class ProbeSettings:
    ecfg_path:str
    nonce:str
    started_at_utc:str
    stop_at_utc:str
    dependency_sha256:str

    def payload(self):
        start,stop=timestamp(self.started_at_utc),timestamp(self.stop_at_utc)
        if (not Path(self.ecfg_path).is_absolute() or not re.fullmatch('[0-9a-f]{32}',self.nonce)
                or not re.fullmatch('[0-9a-f]{64}',self.dependency_sha256)
                or stop-start!=timedelta(seconds=HARD_SECONDS)):
            raise ValueError('Explicit fixed probe configuration required')
        return {'contract':CONTRACT,'ecfg_path':str(Path(self.ecfg_path).resolve()),'nonce':self.nonce,
            'started_at_utc':start.isoformat(),'stop_at_utc':stop.isoformat(),
            'dependency_sha256':self.dependency_sha256}


def _silence():
    logging.disable(logging.CRITICAL)
    fd=os.open(os.devnull,os.O_WRONLY)
    try:os.dup2(fd,1);os.dup2(fd,2)
    finally:os.close(fd)


def run_child(settings,expected,*,clock=None,inventory=None,secure_api=None):
    """Private stdout duplicate carries only our fixed-schema receipt."""
    channel=os.dup(1)
    _silence()
    clock=clock or (lambda:datetime.now(timezone.utc))
    state={'contract':CONTRACT,'nonce':settings.nonce,'result':'FAILED','reason':'startup_failed',
        'symbol':SYMBOL,'quote_dispatch_permits':0,'quote_response_returned':False,
        'http_status':None,'returned_symbol_matches':False,'client_close_invoked':False,
        'dependency_sha256':settings.dependency_sha256}
    done,startup_done=threading.Event(),threading.Event()
    lock=threading.Lock();emitted=False
    def emit(reason=None):
        nonlocal emitted
        with lock:
            if emitted:return
            if reason:state.update(result='FAILED',reason=reason)
            encoded=(canonical(state)+'\n').encode()
            if len(encoded)>MAX_REPORT_BYTES:os._exit(70)
            os.write(channel,encoded);emitted=True
    def watchdog(event,seconds):
        if not event.wait(max(0,seconds)):
            try:emit('probe_deadline_ended')
            finally:os._exit(124)
    client=password=None
    try:
        settings.payload()
        remaining=(timestamp(settings.stop_at_utc)-clock()).total_seconds()
        if not 0<remaining<=HARD_SECONDS:raise StartupError('window_ended')
        threading.Thread(target=watchdog,args=(done,remaining),daemon=True).start()
        threading.Thread(target=watchdog,args=(startup_done,min(8,remaining)),daemon=True).start()
        observed=(inventory or inspect_dependencies)(expected)
        if not observed['qualified'] or digest(observed)!=settings.dependency_sha256:
            state['reason']=observed['reason'] if not observed['qualified'] else 'dependency_source_mismatch'
            return 70
        password=receive_password(sys.stdin.buffer,settings.nonce)
        client=prepare_authenticated_client(AuthStartupSettings(settings.ecfg_path,settings.stop_at_utc),
            password,clock=clock,secure_api=secure_api)
        password[:]=b'\0'*len(password);password.clear()
        startup_done.set()
        if clock()>=timestamp(settings.stop_at_utc):raise StartupError('window_ended')
        state['quote_dispatch_permits']=1
        response=client.quotes([SYMBOL],fields='all')
        state.update(quote_response_returned=True,http_status=response.status_code)
        if getattr(client,'halt_reason',None):raise StartupError(client.halt_reason)
        if not response.ok:
            state['reason']='provider_failed';return 70
        value=response.json()
        entry=value.get(SYMBOL) if isinstance(value,dict) else None
        price=entry.get('quote',{}).get('lastPrice') if isinstance(entry,dict) and isinstance(entry.get('quote'),dict) else None
        valid=(isinstance(entry,dict) and entry.get('symbol')==SYMBOL
            and type(price) in (int,float) and math.isfinite(price) and price>0)
        state['returned_symbol_matches']=valid
        if not valid:state['reason']='provider_quote_invalid';return 70
        if clock()>=timestamp(settings.stop_at_utc):raise StartupError('window_ended')
        state.update(result='PASS',reason='probe_pass')
        return 0
    except StartupError as error:
        state['reason']=error.code;return 70
    except KeyboardInterrupt:
        state['reason']='operator_interrupted';return 130
    except Exception:
        state['reason']='startup_failed';return 70
    finally:
        if password is not None:password[:]=b'\0'*len(password);password.clear()
        if client is not None:
            state['client_close_invoked']=True
            client.close()
        startup_done.set();done.set()
        emit();os.close(channel)


def parse_receipt(raw,settings):
    """Reject unexpected text; never echo or save it, even on parse failure."""
    try:
        if len(raw)>MAX_REPORT_BYTES:raise ValueError()
        value=json.loads(raw)
        if (set(value)!={'contract','nonce','result','reason','symbol','quote_dispatch_permits',
                'quote_response_returned','http_status','returned_symbol_matches','client_close_invoked','dependency_sha256'}
                or value['contract']!=CONTRACT or value['nonce']!=settings.nonce or value['symbol']!=SYMBOL
                or value['dependency_sha256']!=settings.dependency_sha256
                or value['result'] not in ('PASS','FAILED') or value['reason'] not in REASONS
                or type(value['quote_dispatch_permits']) is not int or value['quote_dispatch_permits'] not in (0,1)
                or any(type(value[k]) is not bool for k in ('quote_response_returned','returned_symbol_matches','client_close_invoked'))
                or value['http_status'] is not None and (type(value['http_status']) is not int or not 100<=value['http_status']<=599)):
            raise ValueError()
        if value['result']=='PASS' and not (value['reason']=='probe_pass' and value['quote_dispatch_permits']==1
                and value['quote_response_returned'] and value['returned_symbol_matches']
                and value['client_close_invoked'] and value['http_status']==200):raise ValueError()
        if (value['result']=='FAILED' and value['reason']=='probe_pass'
                or value['quote_response_returned'] and value['quote_dispatch_permits']!=1
                or value['returned_symbol_matches'] and not value['quote_response_returned']):raise ValueError()
        return value
    except Exception:raise StartupError('startup_failed') from None


def stop_exact_child(child):
    if child.poll() is None:
        child.terminate()
        try:child.wait(timeout=1)
        except subprocess.TimeoutExpired:child.kill();child.wait(timeout=1)


def run_probe(ecfg_path,output_root,expected,child_command,*,inventory=None,prompt=None,
              hard_seconds=HARD_SECONDS):
    """The CLI fixes the deadline; injectable callables support offline tests."""
    observed=(inventory or inspect_dependencies)(expected)
    report={'contract':CONTRACT,'result':'BLOCKED','reason':observed['reason'],'dependencies':observed,
        'symbol':SYMBOL,'maximum_quote_dispatches':1,'reserved_quote_budget':0,
        'quote_dispatch_permits':None,'child_receipt':None,'child_returncode':None,
        'owned_child_exit_observed':False,'request_timeout_seconds':3,'startup_timeout_seconds':8,
        'hard_seconds':hard_seconds,'network_scope':'installed_client_and_one_quote_only',
        'native_polling_started':False,'nasdaq_requests':0,'production_journal_or_process_access':False,
        'shared_sdk_token_refresh_possible':True,'market_freshness_or_capacity_qualified':False}
    source=child=frame=None
    try:
        if not Path(ecfg_path).is_absolute() or not 0<hard_seconds<=HARD_SECONDS:raise ValueError()
        if not observed['qualified']:return save_report(output_root,report)
        nonce=uuid.uuid4().hex
        source=(prompt or SessionPassword.prompt)(digest({'contract':CONTRACT,'nonce':nonce,
            'ecfg_path':str(Path(ecfg_path).resolve()),'dependencies':digest(observed)}))
        start=datetime.now(timezone.utc)
        settings=ProbeSettings(str(ecfg_path),nonce,start.isoformat(),
            (start+timedelta(seconds=HARD_SECONDS)).isoformat(),digest(observed))
        payload=settings.payload();payload.pop('contract')
        frame=source.frame(nonce)
        child=subprocess.Popen([*child_command,json.dumps(payload)],stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
        report['reserved_quote_budget']=1
        try:
            raw,_=child.communicate(input=frame,timeout=hard_seconds)
        except subprocess.TimeoutExpired:
            stop_exact_child(child);child.communicate()
            report.update(result='FAILED',reason='probe_deadline_ended');return save_report(output_root,report,child)
        report['owned_child_exit_observed']=True;report['child_returncode']=child.returncode
        try:receipt=parse_receipt(raw,settings)
        except StartupError:
            report.update(result='FAILED',reason='child_protocol_invalid');return save_report(output_root,report,child)
        report.update(child_receipt=receipt,quote_dispatch_permits=receipt['quote_dispatch_permits'],
            result=receipt['result'] if child.returncode==0 else 'FAILED',
            reason=receipt['reason'] if child.returncode==0 or receipt['result']=='FAILED' else 'startup_failed')
    except KeyboardInterrupt:report.update(result='FAILED',reason='operator_interrupted')
    except StartupError as error:report.update(result='FAILED',reason=error.code)
    except Exception:report.update(result='FAILED',reason='startup_failed')
    finally:
        if child is not None:stop_exact_child(child)
        if frame is not None:frame[:]=b'\0'*len(frame)
        if source is not None:source.close()
    return save_report(output_root,report,child)


def save_report(root,report,child=None):
    if child is not None:
        report['child_returncode']=child.returncode
        report['owned_child_exit_observed']=child.poll() is not None
    folder=Path(root)/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8])
    folder.mkdir(parents=True,exist_ok=False)
    atomic_json(folder/'report.json',report)
    return folder/'report.json',report
