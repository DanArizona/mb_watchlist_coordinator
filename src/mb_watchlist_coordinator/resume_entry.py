"""Private-pipe manual-reopen boundary; no operator/live command is exposed."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import threading

from .authenticated_startup import StartupError, receive_password, CODES as AUTH_CODES
from .controller_bootstrap import strict_json
from .controller_resume import ResumeSettings, ResumeError, resume_manual, CONTRACT, CODES
from .installed_startup_probe import _silence
from .sampling_requests import digest, timestamp

ENTRY_CODES = CODES | AUTH_CODES | {'resume_ready','credential_deadline_ended','preparation_deadline_ended'}


def run_entry(configuration, configuration_sha256, *, stream=None, clock=None,
              inventory=None, secure_api=None, feed_factory=None, fault_hook=None,
              on_ready=None, credential_seconds=8, hard_seconds=60):
    """Owned process boundary for preparation, not the outer live-profile loop.

    Trusted callbacks/drivers are offline seams. Arbitrary SDK/callback errors
    cannot reach the inherited report pipe, files, argv or environment.
    """
    channel=os.dup(1);_silence()
    clock=clock or (lambda:datetime.now(timezone.utc))
    done,authenticated=threading.Event(),threading.Event();lock=threading.Lock()
    emitted=False;password=runtime=None;return_code=70
    safe_sha=configuration_sha256 if type(configuration_sha256) is str and re.fullmatch('[0-9a-f]{64}',configuration_sha256) else None
    state={'contract':CONTRACT,'configuration_sha256':safe_sha,'result':'FAILED',
        'reason':'configuration_invalid','reopened':False,'client_close_invoked':False,
        'native_poll_run_registered_by_reopen':False,'directory_attempts_started':0,
        'feed_attempts_started_by_reopen':0,'quote_dispatches_started_by_reopen':0,
        'outer_profile_harness_qualified':False,'production_access':False}
    def emit(reason=None):
        nonlocal emitted
        with lock:
            if emitted:return
            if reason:state.update(result='FAILED',reason=reason)
            os.write(channel,(json.dumps(state,sort_keys=True)+'\n').encode());emitted=True
    def watch(event,seconds,reason):
        if not event.wait(seconds):
            try:emit(reason)
            finally:os._exit(124)
    def arm(event,seconds,reason):
        threading.Thread(target=watch,args=(event,max(0,seconds),reason),daemon=True).start()
    try:
        if (safe_sha is None or not 0<credential_seconds<=8 or not 0<hard_seconds<=60
                or not callable(feed_factory)):
            raise ResumeError('configuration_invalid')
        arm(done,hard_seconds,'preparation_deadline_ended')
        arm(authenticated,credential_seconds,'credential_deadline_ended')
        path=Path(configuration)
        if not path.is_file() or path.is_symlink() or path.stat().st_size>2_000_000:
            raise ResumeError('configuration_invalid')
        raw=strict_json(path.read_text(encoding='utf-8'));raw['worker_command']=tuple(raw['worker_command'])
        settings=ResumeSettings(**raw)
        if digest(settings.public())!=safe_sha:raise ResumeError('configuration_invalid')
        binding=strict_json((Path(settings.experiment_root)/'runtime-binding.json').read_text())
        remaining=min(hard_seconds,(timestamp(settings.submitted_at_utc)-clock()).total_seconds()+60,
            (timestamp(binding['stop_at_utc'])-clock()).total_seconds())
        if remaining<=0:raise ResumeError('resume_deadline_ended')
        arm(done,remaining,'preparation_deadline_ended')
        password=receive_password(sys.stdin.buffer if stream is None else stream,settings.nonce)
        def stage(name):
            if name=='credentials_accepted':authenticated.set()
            if fault_hook:fault_hook(name)
        runtime=resume_manual(settings,password,feed_factory=feed_factory,clock=clock,
            inventory=inventory,secure_api=secure_api,fault_hook=stage)
        state['reopened']=True
        if on_ready:on_ready(runtime)
        state.update(result='PASS',reason='resume_ready')
        return_code=0
    except (ResumeError,StartupError) as error:
        state['reason']=error.code if error.code in ENTRY_CODES else 'resume_failed'
        return_code=70
    except KeyboardInterrupt:
        state['reason']='operator_interrupted';return_code=130
    except Exception:
        state['reason']='resume_failed';return_code=70
    finally:
        if isinstance(password,bytearray):password[:]=b'\0'*len(password);password.clear()
        if runtime is not None:
            try:
                runtime.close();state['client_close_invoked']=True
            except Exception:
                state.update(result='FAILED',reason='resume_failed')
                return_code=70
        authenticated.set();done.set();emit();os.close(channel)
    return return_code


def parse_receipt(raw,configuration_sha256):
    try:
        if len(raw)>8192:raise ValueError()
        value=strict_json(raw)
        if (set(value)!={'contract','configuration_sha256','result','reason','reopened',
                    'client_close_invoked','native_poll_run_registered_by_reopen','directory_attempts_started',
                    'feed_attempts_started_by_reopen','quote_dispatches_started_by_reopen',
                    'outer_profile_harness_qualified','production_access'}
                or value['contract']!=CONTRACT or value['configuration_sha256']!=configuration_sha256
                or value['result'] not in ('PASS','FAILED') or value['reason'] not in ENTRY_CODES
                or any(type(value[k]) is not bool for k in ('reopened','client_close_invoked',
                    'native_poll_run_registered_by_reopen','outer_profile_harness_qualified','production_access'))
                or any(type(value[k]) is not int or value[k]!=0 for k in ('directory_attempts_started',
                    'feed_attempts_started_by_reopen','quote_dispatches_started_by_reopen'))
                or any(value[k] for k in ('native_poll_run_registered_by_reopen','outer_profile_harness_qualified','production_access'))
                or (value['result']=='PASS')!=(value['reason']=='resume_ready')
                or value['result']=='PASS' and not (value['reopened'] and value['client_close_invoked'])):
            raise ValueError()
        return value
    except Exception:raise ResumeError('resume_failed') from None
