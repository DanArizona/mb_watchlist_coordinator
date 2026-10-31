"""One paced broker gate over the existing Nasdaq outbox and manual receipts."""
from contextlib import closing

from .daily_broker_admission import CONTRACT
from .daily_identity_manual_controls import gate_command_id
from .daily_multi_identity import MultiIdentityGate
from .integrated_identity import IdentityStopRequired
from .nasdaq_sampling import _intent
from .sampling_requests import canonical,digest,freeze,plain,timestamp
from .sampling_service import owner_lock


class SharedManualDelivery:
    def __init__(self,nasdaq,manual):
        self.nasdaq,self.manual=nasdaq,manual
        self.path,self.live,self.recovery,self.requests=nasdaq.path,nasdaq.live,nasdaq.recovery,nasdaq.requests
        self.producer_id=nasdaq.producer_id
        self.identity=freeze(self._identity())

    def _identity(self):
        return {'contract':'daily-nasdaq-manual-identity-outbox-v1','producer_id':self.producer_id,
            'nasdaq_delivery':plain(self.nasdaq.identity),'manual_controls':plain(self.manual.identity)}

    def reconcile(self,**kwargs):return self.nasdaq.reconcile(**kwargs)

    def snapshot(self):
        if canonical(self._identity())!=canonical(self.identity):raise ValueError('Shared identity outbox binding changed')
        source=plain(self.nasdaq.snapshot())
        _,commands,results=self.manual._read()
        for cid,requested in commands.items():
            command=requested['command']
            if command['action']!='promote'or command['symbol']in self.requests.baseline.uni:continue
            key=gate_command_id(cid)
            if key in source['commands']:raise ValueError('Manual and Nasdaq identity command IDs collide')
            normalized={'source':'manual','producer_id':self.manual.actor_id,'manual_command_id':cid,
                'symbol':command['symbol'],'created_at_utc':requested['at_utc'],
                'sampling_channel':command['target'],'reason':command['reason']}
            source['commands'][key]={'command':normalized}
            receipt=results.get(cid)
            if receipt is None:source['pending'].append(key)
            elif receipt['backend_sequence']is not None:
                source['deliveries'][key]={'accepted':receipt['accepted'],'request_sequence':receipt['backend_sequence']}
        source['pending'].sort(key=lambda key:(source['commands'][key]['command']['created_at_utc'],key))
        return freeze(source)


class SharedManualIdentityGate(MultiIdentityGate):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        value=plain(self.identity)
        value.update(contract=CONTRACT,request_admission_sha256=digest(self.requests.admission.payload()),
            sources=['nasdaq-shared-daily','operator:masterbot'])
        self.identity=freeze(value)

    def _inputs(self,c):
        value=super()._inputs(c)
        from .daily_multi_publication import MultiPublicationService
        return value+(MultiPublicationService._rows(self.delivery.manual.path,None),)

    def deliver_pending(self,*,client,after_submit=None,fault_hook=None):
        with owner_lock(self.gate_path.with_suffix('.identity-owner.lock')):
            snap=plain(self.snapshot())
            # Settle an already unknown/blocked manual outcome without retrying
            # its broker reservation. One command is handled per ordinary pump.
            settle=[cid for cid in snap['identity_gate']['all_outbox_pending']
                if snap['commands'][cid]['command'].get('source')=='manual'
                and cid in snap['identity_gate']['dispositions']]
            pending=settle or snap['pending']
            if not pending:return ()
            cid=pending[0];command=snap['commands'][cid]['command']
            code=self._authorize(cid,client,fault_hook=fault_hook)
            if code=='provider_stop_required':raise IdentityStopRequired(code)
            if command.get('source')=='manual':
                if code=='deferred_identity_spacing':return ()
                self.delivery.manual.retry(command['manual_command_id'])
                self.snapshot()
                return ()
            if code!='approved':return ()
            delivery=self.delivery.nasdaq
            with closing(delivery._connect(write=True))as c,c:
                c.execute('BEGIN IMMEDIATE');_,queued,acks,_=delivery._read(c)
                if cid in acks:return ()
                if self.stop_requested()or not self.start<=self.clock()<self.stop:
                    raise IdentityStopRequired('profile_window_or_stop')
                entry=queued[cid]
                candidates=[k for k,v in acks.items()if v['accepted']and'reused_request_id'not in v]
                alias=self.requests.reuse_active_request(_intent(entry['command']),actor_id=self.producer_id,candidate_request_ids=candidates)
                result=self.requests.submit_request(_intent(entry['command']),actor_id=self.producer_id)
                if after_submit:after_submit(result)
                c.execute('INSERT INTO delivery_ack VALUES(?,?)',(cid,canonical(delivery._ack(entry,result.event,alias))))
        self.snapshot()
        return(result,)
