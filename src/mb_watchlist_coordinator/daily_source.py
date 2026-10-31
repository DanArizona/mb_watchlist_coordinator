"""Daily source-to-publication pump, inside an explicitly bounded owner.

This API owns only its feed child. Native collection is an independent role;
verified demand survives feed loss. No live launcher or authentication here.
"""
from pathlib import Path
import json
import os
import sqlite3

from .daily_feed import DailyFeedClient,DailyFeedLimits,DailyFeedTransport
from .nasdaq_recovery_supervisor import NasdaqRecoverySupervisor,_failure_details
from .sampling_requests import canonical,freeze,plain,digest,utc_text
from .sampling_service import owner_lock,ServiceBusy
from .recovery_workers import atomic_json


class _Delivery:
    def __init__(self,session,client):
        self.session,self.gate,self.client=session,session.gate,client
        self.path,self.live,self.recovery,self.requests=self.gate.path,self.gate.live,self.gate.recovery,self.gate.requests
        self.identity=freeze({'contract':'daily-prepared-identity-delivery-v1',
            'gate':plain(self.gate.identity),'daily_binding_sha256':session.binding['binding_sha256']})

    def snapshot(self):return self.gate.snapshot()
    def reconcile(self,**kwargs):return self.gate.reconcile(**kwargs)
    def deliver_pending(self):
        self.session.validate()
        return self.gate.deliver_pending(client=self.client)


class _Authority(NasdaqRecoverySupervisor):
    def cycle(self,**kwargs):
        from .operating_plan import MULTI_PROFILE
        if self.delivery.session.settings.policy_profile!=MULTI_PROFILE:
            return super().cycle(**kwargs)
        # An authority ownership failure and a nested publication read/write
        # collision are different. Never replay an entire operation on either.
        lease=owner_lock(self.path.with_suffix('.owner.lock'))
        try:lease.__enter__()
        except ServiceBusy:
            return {'status':'BLOCKED','detail':'Authority already owned','status_persisted':False}
        try:
            return self._cycle(**kwargs)
        except ServiceBusy:
            return {'status':'WAITING','detail':'publication_evidence_busy','status_persisted':False,
                'discovery_scope_reconciled':False,'operation_retried':False}
        finally:lease.__exit__(None,None,None)

    def _identity(self):
        value=super()._identity()
        value.update(contract='daily-nasdaq-publication-authority-v1',production_access=True,
            unmanaged_channels=['uni','focus','health','collector'],
            readiness_scope='declared_daily_feed_reconciliation_and_native_publication_only')
        return value

    def _report(self,status,reasons,**details):
        if (status=='RECOVERING' and details.get('local_membership_effective')
                and details.get('discovery_scope_reconciled')
                and details.get('worker',{}).get('status')=='NOT_CONFIGURED'):
            # This authority reports source/publication readiness. The separately
            # owned collector is deliberately outside its readiness scope.
            status='READY_WITH_GAPS' if reasons else 'READY'
        details.update(production_access=True,
            unmanaged_channels_untouched=['uni','focus','health','collector'])
        return super()._report(status,reasons,**details)


class DailySourcePump:
    def __init__(self,session,*,identity_client,limits=None,clock=None,feed_client_factory=None,
                 allow_network=False,stop_requested=lambda:False):
        self.session=session;self.clock=clock or session.clock
        session.validate()
        if not callable(getattr(identity_client,'quotes',None)):
            raise ValueError('Prepared bounded identity client required')
        limits=limits or DailyFeedLimits()
        if limits.max_attempts>session.binding['policy']['limits']['maximum_feed_attempts']:
            raise ValueError('Daily feed attempt ceiling exceeds the bound review candidate')
        self.transport=DailyFeedTransport(session.root/'daily-feed.sqlite3',
            session_date=session.requests.session_date,queries=session.recovery.settings.queries,
            limits=limits,clock=self.clock)
        self.client=(feed_client_factory or (lambda transport:DailyFeedClient(transport,
            allow_network=allow_network)))(self.transport)
        if self.client.transport is not self.transport:raise ValueError('Feed client transport binding differs')
        self.stop_requested=stop_requested
        self.delivery=_Delivery(session,identity_client)
        self.authority=_Authority(session.root/'daily-source.sqlite3',feed_client=self.client,
            delivery=self.delivery,service=session.service,clock=self.clock)
        self.initialized,self.closed=False,False
        self.lease=None
        self.claim_path=Path(session.settings.journal_path).with_suffix('.daily-feed-session.json')
        self.ready_path=session.root/'daily-source-ready.json'
        self.claim={'contract':'daily-source-invocation-v1',
            'daily_binding_sha256':session.binding['binding_sha256'],
            'feed_identity':plain(self.transport.identity),'authority_identity':plain(self.authority.identity)}

    def initialize(self,*,create=False):
        if self.initialized or self.closed:raise ValueError('Fresh source pump object required')
        self.session.validate()
        lease=owner_lock(Path(self.session.settings.journal_path).with_suffix('.daily-source-owner.lock'))
        lease.__enter__();self.lease=lease
        try:
            if create:
                if any(p.exists() for p in (self.claim_path,self.ready_path,self.transport.path,self.authority.path)):
                    raise ValueError('Original daily source state must be restored, never reset')
                with self.claim_path.open('x',encoding='utf-8') as out:
                    out.write(canonical(self.claim)+'\n');out.flush();os.fsync(out.fileno())
            elif (self.claim_path.is_symlink() or self.ready_path.is_symlink() or
                    json.loads(self.claim_path.read_text())!=self.claim or
                    json.loads(self.ready_path.read_text())!={'claim':self.claim,'status':'INITIALIZED'}):
                raise ValueError('Original complete daily source binding required')
            self.transport.initialize(create=create)
            self.authority.initialize(create=create)
            if create:atomic_json(self.ready_path,{'claim':self.claim,'status':'INITIALIZED'})
            self.initialized=True
            return self.authority.snapshot()
        except BaseException:
            self.close();raise

    def cycle(self,*,synthetic=None):
        if not self.initialized or self.closed:raise ValueError('Owned initialized daily source pump required')
        try:
            report=self._cycle(synthetic=synthetic)
        except (ValueError,OSError,sqlite3.Error,KeyError,TypeError) as error:
            details=_failure_details(error)
            try:self.client.close_owned()
            except (ValueError,OSError,sqlite3.Error,KeyError,TypeError) as cleanup:
                details['feed_cleanup_error_type']=type(cleanup).__name__
            try:report=self.authority._report('BLOCKED',[type(error).__name__],detail=str(error),**details)
            except (ValueError,OSError,sqlite3.Error,KeyError,TypeError):
                report={'status':'BLOCKED','reasons':[type(error).__name__],
                    'detail':str(error),'status_persisted':False,**details}
            error.source_failure_report=self._failure_receipt(report)
            raise  # Preserve the pre-existing caller exception/cleanup contract.
        if report['status']=='BLOCKED':
            report=self._failure_receipt(report)
        if report['status']=='WINDOW_ENDED':self.close()
        return dict(report,source_only=True,collector_managed=False,live_launch_available=False)

    def _failure_receipt(self,report):
        try:
            value={'contract':'daily-source-failure-v1',
                'daily_binding_sha256':self.session.binding['binding_sha256'],
                'observed_at_utc':utc_text(self.clock()),'report':plain(report)}
            value['content_sha256']=digest(value)
            atomic_json(self.session.root/'daily-source-failure.json',value)
            return dict(report,failure_receipt_saved=True)
        except (ValueError,OSError,sqlite3.Error,KeyError,TypeError) as error:
            return dict(report,failure_receipt_saved=False,failure_receipt_error_type=type(error).__name__)

    def _cycle(self,*,synthetic=None):
        self.session.validate()
        if (json.loads(self.claim_path.read_text())!=self.claim or
                json.loads(self.ready_path.read_text())!={'claim':self.claim,'status':'INITIALIZED'}):
            raise ValueError('Daily source invocation binding changed')
        if self.clock()>=self.transport.stop:
            return self.authority._report('WINDOW_ENDED',['target_regular_close'])
        if self.clock()<self.transport.start:
            return self.authority._report('WAITING',['target_open_pending'])
        return self.authority.cycle(synthetic=synthetic,
            stop_requested=lambda:self.stop_requested() or self.clock()>=self.transport.stop)

    def close(self):
        if not self.closed:
            self.closed=True
            try:self.client.close_owned()
            finally:
                if self.lease is not None:
                    lease,self.lease=self.lease,None
                    lease.__exit__(None,None,None)
