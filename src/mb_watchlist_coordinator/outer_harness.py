"""Independent owner of a gated controller and a separate reporting process.

Trusted caller supplies reviewed entries. No implicit live launcher, password
prompt, PID adoption, source fetch or production journal/process operation.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import time

from .outer_deadline import OuterBounds
from .owned_process_scope import OwnedProcessScope
from .recovery_workers import atomic_json, _write_handoff
from .sampling_requests import timestamp, utc_text


@dataclass(frozen=True)
class OuterSchedule:
    submitted_at_utc: str
    start_at_utc: str
    stop_at_utc: str

    def validate(self):
        submitted,start,stop=map(timestamp,(self.submitted_at_utc,self.start_at_utc,self.stop_at_utc))
        if not 60<=(start-submitted).total_seconds()<61 or stop-start!=timedelta(seconds=720):
            raise ValueError('Original frozen 60s lead/720s window required')
        return submitted,start,stop


def read_status(path, nonce):
    if not path.exists():return None
    if path.is_symlink() or path.stat().st_size>8192:raise ValueError('Unsafe controller status')
    value=json.loads(path.read_text())
    if (set(value)!={'contract','nonce','phase'} or value['contract']!='outer-controller-status-v1'
            or value['nonce']!=nonce or value['phase'] not in ('BOOTSTRAPPING','ACTIVE','GOAL_COMPLETE','FAILED')):
        raise ValueError('Controller status binding differs')
    return value


class OuterHarness:
    def __init__(self, root, schedule, nonce, *, clock=None, monotonic=time.monotonic, sleep=time.sleep,
                 entry_mode='fresh', preparation_submitted_at_utc=None, expected_preflight_sha256=None):
        import re
        self.root=Path(root)
        if (not self.root.is_absolute() or self.root!=self.root.resolve()
                or not self.root.name.startswith('outer_') or self.root.exists()
                or any(p.lower().startswith('quote_observation_journal') for p in self.root.parts)
                or not re.fullmatch('[0-9a-f]{32}',nonce)):
            raise ValueError('Fresh explicit experimental outer root required')
        self.schedule,self.nonce=schedule,nonce
        self.submitted,self.start,self.stop=schedule.validate()
        self.clock=clock or (lambda:datetime.now(timezone.utc));self.monotonic,self.sleep=monotonic,sleep
        now=self.clock();mono=monotonic()
        if not self.submitted<=now<self.stop:raise ValueError('Original window ended or clock differs')
        if entry_mode not in ('fresh','manual_resume') or entry_mode=='fresh' and preparation_submitted_at_utc is not None:
            raise ValueError('Explicit fresh or new-human resume entry required')
        preparation=self.submitted if entry_mode=='fresh' else timestamp(preparation_submitted_at_utc)
        if not self.submitted<=preparation<=now:raise ValueError('Preparation observation differs')
        self.preparation_end=min(preparation+timedelta(seconds=60),self.stop)
        self.entry_mode=entry_mode
        if expected_preflight_sha256 is not None and not re.fullmatch('[0-9a-f]{64}',expected_preflight_sha256):
            raise ValueError('Expected preflight binding differs')
        self.expected_preflight_sha256=expected_preflight_sha256
        self.bootstrap_end=mono+max(0,(self.preparation_end-now).total_seconds())
        self.bounds=OuterBounds(mono+(self.stop-now).total_seconds())
        self.status_path=self.root/'controller-status.json';self.stop_path=self.root/'STOP.json'
        self.result_path=self.root/'outer-result.json';self.used=False

    def _pause(self, deadline):
        self.sleep(min(.02,max(0,deadline-self.monotonic())))

    def run(self, controller_command, *, reporter_command=None, credential_frame=None,
            stop_requested=lambda:False):
        if self.used:raise ValueError('Outer invocation cannot restart/reset its window')
        if credential_frame is not None and type(credential_frame) is not bytearray:
            raise ValueError('RAM-only credential frame required')
        self.used=True;self.root.mkdir(parents=True,exist_ok=False)
        atomic_json(self.root/'binding.json',{'nonce':self.nonce,'schedule':self.schedule.__dict__,
            'expected_preflight_sha256':self.expected_preflight_sha256,
            'contract':'owned-outer-hot-profile-v1','production_access':False})
        scope=OwnedProcessScope(controller_command,self.nonce,monotonic=self.monotonic)
        reason='controller_failed';phase=None;cleanup=None;report_cleanup=None;report_exit=None
        failure=None
        try:
            scope.launch()
            if self.monotonic()>=self.bounds.active_end or self.clock()>=self.stop:
                reason='active_deadline_ended'
            else:
                scope.open_gate()
                if credential_frame is not None:
                    if type(credential_frame) is not bytearray:raise ValueError('RAM-only credential frame required')
                    import threading
                    outcome={}
                    threading.Thread(target=_write_handoff,args=(scope.child.stdin,credential_frame,outcome),daemon=True).start()
                while True:
                    now=self.monotonic()
                    status=read_status(self.status_path,self.nonce)
                    phase=status['phase'] if status else None
                    if stop_requested():reason='operator_stop';break
                    if now>=self.bounds.active_end or self.clock()>=self.stop:reason='active_deadline_ended';break
                    if phase=='GOAL_COMPLETE':reason='profile_goal';break
                    if phase=='FAILED':reason='controller_failed';break
                    if scope.child.poll() is not None:reason='controller_exited_before_goal';break
                    # A terminal controller state retains its actual cause even
                    # when it is first observed after the preparation endpoint.
                    if phase not in ('ACTIVE','GOAL_COMPLETE') and (now>=self.bootstrap_end or self.clock()>=self.preparation_end):
                        reason='bootstrap_deadline_ended';break
                    self._pause(min(self.bounds.active_end,self.bootstrap_end if phase!='ACTIVE' else self.bounds.active_end))
        except KeyboardInterrupt:
            reason='operator_stop'
        except Exception as error:
            reason='outer_protocol_or_launch_failed'
            failure={'exception_type':type(error).__name__,
                'errno':getattr(error,'errno',None) if type(getattr(error,'errno',None)) is int else None,
                'winerror':getattr(error,'winerror',None) if type(getattr(error,'winerror',None)) is int else None}
        finally:
            stopped=self.monotonic();stop_utc=utc_text(self.clock());bounds=self.bounds.stopped_at(stopped)
            stop_saved=True
            try:atomic_json(self.stop_path,{'nonce':self.nonce,'reason':reason,'acquisition_stop_requested_at_utc':stop_utc})
            except OSError:stop_saved=False
            # Cooperative close has only a small part of the SAME cleanup budget.
            grace=min(bounds.cleanup_end,stopped+.5)
            try:
                while scope.child is not None and scope.child.poll() is None and self.monotonic()<grace:self._pause(grace)
                if not scope.closed:cleanup=scope.finish(bounds.cleanup_end,sleep=self.sleep)
                else:cleanup={'status':'CLEANUP_INCOMPLETE','reason':'scope_launch_failed'}
            except Exception:cleanup={'status':'CLEANUP_INCOMPLETE','reason':'scope_cleanup_failed'}
            if credential_frame is not None:
                credential_frame[:]=b'\0'*len(credential_frame)
            reporting_end=min(bounds.report_end,self.monotonic()+60)
            if reporter_command is not None and cleanup['status']=='EXIT_OBSERVED':
                reporter=OwnedProcessScope(reporter_command,self.nonce,monotonic=self.monotonic)
                try:
                    if self.monotonic()>=reporting_end:raise TimeoutError()
                    reporter.launch();reporter.open_gate()
                    while reporter.child.poll() is None and self.monotonic()<reporting_end:self._pause(reporting_end)
                    report_exit=reporter.child.poll()
                except Exception:report_exit=None
                finally:
                    if not reporter.closed:report_cleanup=reporter.finish(reporting_end,sleep=self.sleep)
            result={'contract':'owned-outer-hot-profile-v1','nonce':self.nonce,'stop_reason':reason,
                'controller_phase':phase,'acquisition_stop_requested_at_utc':stop_utc,
                'cleanup':cleanup,'reporter_cleanup':report_cleanup,'reporter_returncode':report_exit,
                'reporting_complete':bool(report_exit==0 and report_cleanup and report_cleanup['status']=='EXIT_OBSERVED'),
                'stop_receipt_saved':stop_saved,
                'failure':failure,
                'result':'STOPPED_EVIDENCE_REQUIRED','production_access':False}
            if reason not in ('profile_goal','active_deadline_ended','operator_stop'):
                result['result']='FAILED'
            elif cleanup['status']!='EXIT_OBSERVED' or reporter_command and not result['reporting_complete']:
                result['result']='INCOMPLETE'
            if not stop_saved:result['result']='FAILED'
            if result['result']=='STOPPED_EVIDENCE_REQUIRED' and result['reporting_complete']:
                try:
                    path=self.root/'native-profile-report.json'
                    if path.is_symlink() or path.stat().st_size>2_000_000:raise ValueError()
                    evidence=json.loads(path.read_text())
                    if (self.expected_preflight_sha256 is None or evidence['outer_nonce']!=self.nonce
                            or evidence['preflight_configuration_sha256']!=self.expected_preflight_sha256
                            or evidence['reporting_read_only'] is not True
                            or evidence['result'] not in ('PASS','PASS_WITH_WARNINGS','READINESS_ONLY','INCOMPLETE','FAILED')):
                        raise ValueError()
                    result['profile_evidence_result']=evidence['result']
                    result['result']=evidence['result']
                    if evidence['result'].startswith('PASS') and reason!='profile_goal':result['result']='INCOMPLETE'
                except (OSError,ValueError,KeyError,TypeError):
                    result['profile_evidence_result']='MISSING_OR_UNBOUND'
                    # Lifecycle-only callers have no native evidence claim.
                    if self.expected_preflight_sha256 is not None:result['result']='FAILED'
            atomic_json(self.result_path,result)
        return result
