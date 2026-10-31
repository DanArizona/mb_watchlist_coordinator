"""Daily controller ownership and an independent outer watchdog.

Trusted callers supply reviewed public configuration and role entries. This
owner never discovers or adopts PIDs, restarts itself, or controls Uni/Focus.
"""
from datetime import datetime, timezone
from pathlib import Path
import re
import threading
import time
from uuid import uuid4

from .authenticated_startup import SessionPassword
from .daily_session import regular_path
from .daily_supervision import DailyWorkerConfiguration, read_json, sealed, unseal
from .owned_process_scope import OwnedProcessScope
from .outer_deadline import OuterBounds
from .recovery_workers import atomic_json, _write_handoff
from .sampling_requests import digest, timestamp, utc_text
from .sampling_service import ServiceBusy, owner_lock

CONTRACT = 'daily-hot-operating-owner-v1'


def load_binding(root):
    root = regular_path(root)
    binding = unseal(read_json(root/'operating-binding.json'))
    if (binding['contract'] != CONTRACT or binding['outer_root'] != str(root)
            or not re.fullmatch('[0-9a-f]{32}', binding['nonce'])
            or not root.name.startswith('daily_outer_')
            or binding['configuration_sha256'] != digest(read_json(root/'configuration.json'))
            or binding['unmanaged_channels'] != ['uni','focus','health']):
        raise ValueError('Original daily operating binding differs')
    return binding


def request_stop(root):
    root = regular_path(root)
    binding = load_binding(root)
    receipt = {'contract':CONTRACT, 'nonce':binding['nonce'],
        'configuration_sha256':binding['configuration_sha256'], 'reason':'operator_stop'}
    atomic_json(root/'STOP.json', sealed(receipt))
    return {'status':'STOP_REQUESTED', 'nonce':binding['nonce'],
        'processes_signaled':False, 'unmanaged_channels_untouched':['uni','focus','health']}


def stop_requested(root, binding):
    path = Path(root)/'STOP.json'
    if not path.exists(): return False
    value = unseal(read_json(path))
    if (value['contract'] != CONTRACT or value['nonce'] != binding['nonce']
            or value['configuration_sha256'] != binding['configuration_sha256']):
        raise ValueError('Daily stop request belongs to another invocation')
    return True


def inspect_operating_status(root, *, clock=None):
    root = regular_path(root)
    now = (clock or (lambda:datetime.now(timezone.utc)))()
    result = {'contract':CONTRACT, 'state':'UNKNOWN', 'provider_access':False,
        'restart_performed':False, 'unmanaged_channels':['uni','focus','health']}
    try:
        binding = load_binding(root)
        result['nonce'] = binding['nonce']
        path = root/'operating-result.json'
        if path.exists():
            value = unseal(read_json(path))
            if (value['nonce'] != binding['nonce']
                    or value['configuration_sha256'] != binding['configuration_sha256']):
                raise ValueError('Daily result binding differs')
            result.update(state=value['result'], stop_reason=value['stop_reason'],
                cleanup=value['cleanup'], reporting=value['reporting'])
            return result
        live = unseal(read_json(root/'operating-live.json'))
        if (live['nonce'] != binding['nonce']
                or live['configuration_sha256'] != binding['configuration_sha256']):
            raise ValueError('Daily outer heartbeat differs')
        age = (now-timestamp(live['observed_at_utc'])).total_seconds()
        with_owner = False
        lease = root/'operating-owner.lock'
        if not lease.is_file(): raise ValueError('Daily outer owner evidence absent')
        try:
            with owner_lock(lease): pass
        except ServiceBusy:
            with_owner = True
        result.update(state=('OWNER_LOST' if not with_owner else
            'STALE_WATCHDOG' if not 0 <= age < 3 else live['phase']), check_age_seconds=age)
        if stop_requested(root,binding): result['stop_requested'] = True
        return result
    except (OSError,ValueError,KeyError,TypeError) as error:
        result['error_type'] = type(error).__name__
        return result


class DailyOperatingOwner:
    """Own one gated controller tree, plus a separately owned final reporter."""
    def __init__(self, root, configuration, *, commands, controller_entry, reporter_entry,
                 mode='fresh', allow_network=False, activation_approved=False,
                 clock=None, monotonic=time.monotonic, sleep=time.sleep):
        if activation_approved is not True:
            raise ValueError('Explicit trusted daily Hot activation assertion required')
        self.root = regular_path(root)
        if (self.root.exists() or not self.root.parent.is_dir()
                or not self.root.name.startswith('daily_outer_')
                or any(p.lower().startswith('quote_observation_journal') for p in self.root.parts)):
            raise ValueError('Fresh separate daily outer directory required')
        if (mode not in ('fresh','manual_resume') or type(allow_network) is not bool
                or set(commands) != {'collector','identity','report'}):
            raise ValueError('Explicit daily invocation mode and worker roles required')
        for command in (*commands.values(),controller_entry,reporter_entry):
            if not isinstance(command,tuple) or not command or not all(type(s) is str and s for s in command):
                raise ValueError('Explicit trusted process entries required')
        self.configuration, self.commands = configuration, commands
        self.controller_entry, self.reporter_entry = controller_entry, reporter_entry
        self.clock = clock or (lambda:datetime.now(timezone.utc))
        self.monotonic, self.sleep = monotonic, sleep
        self.raw = configuration.payload()
        for boundary in (Path(configuration.publication.journal_path).parent,Path(configuration.publication.state_root)):
            if self.root==boundary or self.root in boundary.parents or boundary in self.root.parents:
                raise ValueError('Daily outer must be separate from journal and controller state')
        self.stop_at = timestamp(configuration.collector.stop_at_utc)
        self.now = self.clock()
        if self.now >= self.stop_at: raise ValueError('Original daily collection window ended')
        remaining = (self.stop_at-self.now).total_seconds()
        if not 0 < remaining <= 24*3600: raise ValueError('Dated daily window required')
        self.bounds = OuterBounds(monotonic()+remaining)
        self.bootstrap_end = monotonic()+min(60,remaining)
        self.binding = {'contract':CONTRACT,'nonce':uuid4().hex,'outer_root':str(self.root),
            'configuration_sha256':digest(self.raw), 'state_root':configuration.publication.state_root,
            'stop_at_utc':utc_text(self.stop_at), 'mode':mode, 'allow_network':allow_network,
            'commands':{role:list(command) for role,command in commands.items()},
            'deadlines':{'bootstrap':60,'watchdog_freshness':3,'cleanup':10,'reporting':60},
            'unmanaged_channels':['uni','focus','health'], 'reporting_owner':'independent_outer'}
        self.used, self.child = False, None

    def _live(self,phase):
        atomic_json(self.root/'operating-live.json',sealed({'contract':CONTRACT,
            'nonce':self.binding['nonce'],'configuration_sha256':self.binding['configuration_sha256'],
            'observed_at_utc':utc_text(self.clock()),'phase':phase}))

    def _child_status(self):
        path = self.root/'controller-status.json'
        if not path.exists(): return None
        value = unseal(read_json(path))
        if (value['nonce'] != self.binding['nonce'] or
                value['configuration_sha256'] != self.binding['configuration_sha256'] or
                value['phase'] not in ('BOOTSTRAPPING','ACTIVE','STOPPED','FAILED')):
            raise ValueError('Daily child status belongs to another invocation')
        return value

    def _driver_fresh(self):
        root = Path(self.configuration.publication.state_root)
        raw = read_json(root/'driver-binding.json')
        live = unseal(read_json(root/'driver-live.json'))
        if (raw['configuration_sha256'] != self.binding['configuration_sha256']
                or live['identity_sha256'] != digest(raw)):
            raise ValueError('Daily driver heartbeat binding differs')
        return live['state']=='RUNNING' and 0 <= (self.clock()-timestamp(live['observed_at_utc'])).total_seconds() < 3

    def run(self, password, *, stop_requested_callback=lambda:False):
        if self.used or not isinstance(password,SessionPassword) or password.identity['configuration_sha256'] != digest(self.raw):
            raise ValueError('One fresh owned invocation and matching manual secret required')
        self.used = True
        self.root.mkdir(exist_ok=False)
        atomic_json(self.root/'configuration.json',self.raw)
        atomic_json(self.root/'operating-binding.json',sealed(self.binding))
        with owner_lock(self.root/'operating-owner.lock'):
            return self._run(password,stop_requested_callback)

    def _run(self,password,stop_callback):
        scope = OwnedProcessScope((*self.controller_entry,str(self.root),self.binding['nonce']),self.binding['nonce'],monotonic=self.monotonic)
        reason, failure, phase = 'controller_failed', None, None
        cleanup, reporting = {'status':'CLEANUP_INCOMPLETE'}, {'status':'NOT_ATTEMPTED'}
        frame = password.frame(self.binding['nonce'])
        try:
            self._live('BOOTSTRAPPING'); scope.launch(); self.child = scope.child; scope.open_gate()
            threading.Thread(target=_write_handoff,args=(scope.child.stdin,frame,{}),daemon=True).start()
            last_live = self.monotonic()
            while True:
                now = self.monotonic()
                if now-last_live >= .5:
                    self._live('ACTIVE' if phase=='ACTIVE' else 'BOOTSTRAPPING');last_live=now
                if stop_callback() or stop_requested(self.root,self.binding): reason='operator_stop';break
                if now >= self.bounds.active_end or self.clock() >= self.stop_at: reason='window_ended';break
                status = self._child_status(); phase=status['phase'] if status else None
                if phase=='FAILED': reason='controller_failed';break
                if phase=='STOPPED': reason='controller_stopped';break
                if scope.child.poll() is not None: reason='controller_exited';break
                if phase!='ACTIVE' and now>=self.bootstrap_end: reason='bootstrap_deadline';break
                if phase=='ACTIVE' and not self._driver_fresh(): reason='controller_progress_stale';break
                self.sleep(.02)
        except KeyboardInterrupt:
            reason='operator_stop'
        except Exception as error:
            reason='operating_evidence_or_launch_failed';failure=type(error).__name__
        finally:
            stopped=self.monotonic();stopped_at=self.clock();bounds=self.bounds.stopped_at(stopped)
            try:
                atomic_json(self.root/'STOP.json',sealed({'contract':CONTRACT,'nonce':self.binding['nonce'],
                    'configuration_sha256':self.binding['configuration_sha256'],'reason':reason}))
                self._live('STOPPING')
            except Exception as error: failure=type(error).__name__
            grace=bounds.cleanup_end-1
            try:
                while scope.child is not None and scope.child.poll() is None and self.monotonic()<grace:
                    self.sleep(.02)
                if not scope.closed: cleanup=scope.finish(bounds.cleanup_end,sleep=self.sleep)
            except Exception as error: cleanup={'status':'CLEANUP_INCOMPLETE','error_type':type(error).__name__}
            frame[:]=b'\0'*len(frame);password.close()
            receipt={'contract':CONTRACT,'nonce':self.binding['nonce'],
                'configuration_sha256':self.binding['configuration_sha256'],'stop_reason':reason,
                'result':'STOPPED' if cleanup['status']=='EXIT_OBSERVED' else 'INCOMPLETE',
                'cleanup':cleanup,'cleanup_seconds':self.monotonic()-stopped,
                'acquisition_stop_requested_at_utc':utc_text(stopped_at),'reporting':{'status':'PENDING'},
                'failure_type':failure,'unmanaged_channels_untouched':['uni','focus','health'],
                'full_day_capacity_qualified':False,'production_activation_inferred':False}
            if reason not in ('operator_stop','window_ended','controller_stopped'): receipt['result']='FAILED'
            # Save stop/cleanup even if the independently bounded reporter fails.
            atomic_json(self.root/'operating-result.json',sealed(receipt))
            if cleanup['status']=='EXIT_OBSERVED':
                try: reporting=self._report(stopped_at,min(bounds.report_end,self.monotonic()+60))
                except Exception as error: reporting={'status':'REPORT_INCOMPLETE','error_type':type(error).__name__}
            receipt['reporting']=reporting
            atomic_json(self.root/'operating-result.json',sealed(receipt))
            self._live('STOPPED')
        return receipt

    def _report(self,stopped_at,deadline):
        state = Path(self.configuration.publication.state_root)
        config = state/'daily-worker.json'
        if not config.exists(): return {'status':'REPORT_INCOMPLETE','reason':'controller_not_initialized'}
        directory=state/'reports';directory.mkdir(exist_ok=True)
        report_id=uuid4().hex
        original=unseal(read_json(state/'driver-state.json'))
        job={'configuration_sha256':self.binding['configuration_sha256'],'report_id':report_id,
            'invocation':original['active_invocation'],'output':str(directory/(report_id+'.json')),
            'audited_at_utc':utc_text(stopped_at)}
        path=directory/(report_id+'.job.json');atomic_json(path,job)
        scope=OwnedProcessScope((*self.reporter_entry,str(self.root),self.binding['nonce'],str(path)),self.binding['nonce'],monotonic=self.monotonic)
        try:
            scope.launch();scope.open_gate()
            while scope.child.poll() is None and self.monotonic()<deadline-1:self.sleep(.02)
            code=scope.child.poll()
        finally:
            cleanup=scope.finish(deadline,sleep=self.sleep) if not scope.closed else {'status':'CLEANUP_INCOMPLETE'}
        if code!=0 or cleanup['status']!='EXIT_OBSERVED':
            return {'status':'REPORT_INCOMPLETE','cleanup':cleanup}
        report=unseal(read_json(Path(job['output'])))
        for name in ('configuration_sha256','report_id','invocation','audited_at_utc'):
            if report[name]!=job[name]: raise ValueError('Unbound or stale daily reporter result')
        return {'status':'COMPLETE','report_path':job['output'],'native_audit_passed':report['native_audit_passed'],
            'two_fresh_replays_equal':report['two_fresh_replays_equal'],'first_replay':report['first_replay'],
            'hot_content_integrity':report.get('hot_content_integrity'),
            'validation_passed':report.get('validation_passed',report['native_audit_passed'] and report['two_fresh_replays_equal']),
            'replay_method':report.get('replay_method','native full event reader'),
            'cleanup':cleanup}
