"""Gated controller/reporter entries for the reviewed daily operating owner."""
from datetime import datetime, timezone
from pathlib import Path
import os
import sys
import threading
import time

from .authenticated_startup import SessionPassword, receive_password
from .daily_controller import DailyController
from .daily_operating import CONTRACT, load_binding, stop_requested
from .daily_session import DailySession
from .daily_supervision import DailyWorkerConfiguration, read_json, sealed, unseal
from .integrated_catalog import DirectoryCatalog
from .owned_process_scope import receive_gate
from .recovery_workers import atomic_json
from .sampling_requests import digest, timestamp, utc_text
from .sampling_service import ServiceBusy, owner_lock


class OperatingController(DailyController):
    """The independent outer owns reporting after its whole producer scope exits."""
    def close(self, *, reason='operator_stop', report=False):
        if report is not False: raise ValueError('Independent outer owns final reporting')
        return super().close(reason=reason,report=False)


class ParentFence:
    def __init__(self,root,binding,clock):
        self.root,self.binding,self.clock=Path(root),binding,clock
        self.stop,self.finished=threading.Event(),threading.Event()
        self.failed=False

    def check(self):
        if load_binding(self.root)!=self.binding: raise ValueError('Daily outer binding changed')
        if stop_requested(self.root,self.binding): return False
        live=unseal(read_json(self.root/'operating-live.json'))
        if (live['nonce']!=self.binding['nonce'] or
                live['configuration_sha256']!=self.binding['configuration_sha256'] or
                live['phase'] not in ('BOOTSTRAPPING','ACTIVE') or
                not 0 <= (self.clock()-timestamp(live['observed_at_utc'])).total_seconds()<3):
            raise ValueError('Daily outer watchdog absent or stale')
        path=self.root/'operating-owner.lock'
        if not path.is_file(): raise ValueError('Daily outer owner absent')
        try:
            with owner_lock(path): pass
        except ServiceBusy:
            return True
        raise ValueError('Daily outer ownership absent')

    def watch(self):
        stopped=None
        while not self.finished.wait(.02):
            if stopped is None:
                try:
                    if self.check(): continue
                except BaseException:
                    self.failed=True
                self.stop.set()
                stopped=time.monotonic()
            if time.monotonic()-stopped>=10:
                # This process is in the outer's owned scope. Native children
                # additionally retain their accepted independent owner fences.
                os._exit(124)

    def start(self):
        if not self.check(): raise ValueError('Daily outer stopped before bootstrap')
        self.thread=threading.Thread(target=self.watch,daemon=True);self.thread.start()

    def close(self):
        self.finished.set()
        if hasattr(self,'thread'):self.thread.join(timeout=.1)


def controller_entry(root,nonce,*,clock=None,stream=None,on_started=None,synthetic_factory=None):
    clock=clock or (lambda:datetime.now(timezone.utc))
    stream=sys.stdin.buffer if stream is None else stream
    receive_gate(stream,nonce)
    root=Path(root);binding=load_binding(root)
    if binding['nonce']!=nonce: raise ValueError('Daily controller ownership gate differs')
    parent=ParentFence(root,binding,clock);parent.start()
    controller=session=password=None
    def status(phase,**fields):
        atomic_json(root/'controller-status.json',sealed({'contract':CONTRACT,'nonce':nonce,
            'configuration_sha256':binding['configuration_sha256'],'phase':phase,**fields}))
    try:
        status('BOOTSTRAPPING')
        raw_secret=receive_password(stream,nonce)
        try:password=SessionPassword(raw_secret,binding['configuration_sha256'])
        finally:
            raw_secret[:]=b'\0'*len(raw_secret);raw_secret.clear()
        if not parent.check(): raise ValueError('Daily outer stopped before attachment')
        config=DailyWorkerConfiguration.load(root/'configuration.json')
        session=DailySession(config.publication,DirectoryCatalog.load(config.catalog_path),clock=clock)
        # The original backend refuses partial/missing/foreign claims. It alone
        # decides whether the exact complete existing attachment may reopen.
        session.attach(create=not session.claim_path.exists(),publication_approved=True)
        controller=OperatingController(session,config,
            commands={k:tuple(v) for k,v in binding['commands'].items()},password=password,
            clock=clock,stop_requested=parent.stop.is_set,allow_network=binding['allow_network'],activation_approved=True)
        controller.initialize(create=binding['mode']=='fresh',
            manual_resume_approved=binding['mode']=='manual_resume')
        status('ACTIVE')
        if on_started is not None:on_started(controller)
        while not parent.stop.is_set() and not controller.stopped():
            controller.step(synthetic=synthetic_factory() if synthetic_factory else None)
            # Source requests are paced at sixty seconds; rerunning the entire
            # source/publication validation graph at 10 Hz consumes CPU without
            # creating new evidence. Independent role/freshness watchdogs keep
            # their original frequency and every dispatch still validates.
            parent.stop.wait(.5)
        controller.close(reason='outer_stop_or_close')
        status('FAILED' if parent.failed or controller.state.read()['terminal'] else 'STOPPED')
    except BaseException as error:
        try:status('FAILED',error_type=type(error).__name__)
        except Exception:pass
        raise
    finally:
        if controller is not None:controller.close(reason='outer_entry_cleanup')
        elif session is not None:session.close()
        if password is not None:password.close()
        parent.close()


def reporter_entry(root,nonce,job_path,*,stream=None):
    from .daily_authenticated_worker import run_report
    stream=sys.stdin.buffer if stream is None else stream
    receive_gate(stream,nonce)
    root=Path(root);binding=load_binding(root)
    if binding['nonce']!=nonce: raise ValueError('Daily reporter gate differs')
    receipt=unseal(read_json(root/'operating-result.json'))
    if (receipt['nonce']!=nonce or receipt['cleanup']['status']!='EXIT_OBSERVED'
            or receipt['configuration_sha256']!=binding['configuration_sha256']):
        raise ValueError('Owned producers must exit before reporting')
    job=read_json(Path(job_path))
    if (job['configuration_sha256']!=binding['configuration_sha256']
            or job['audited_at_utc']!=receipt['acquisition_stop_requested_at_utc']):
        raise ValueError('Daily report cutoff differs')
    return run_report(Path(binding['state_root'])/'daily-worker.json',job_path)
