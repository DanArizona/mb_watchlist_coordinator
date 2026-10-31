"""Durable manual identity queue. Only the controller executes broker lookups."""
from .daily_broker_admission import BrokerManualAdmissionPolicy,identity_proof
from .manual_membership import ManualMembershipControls
from .sampling_requests import freeze,plain,timestamp
from .session import session_start


def gate_command_id(command_id):return 'manual:'+command_id


class IdentityQueuedManualControls(ManualMembershipControls):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        if not isinstance(self.requests.admission,BrokerManualAdmissionPolicy):
            raise ValueError('Explicit broker-enabled manual admission required')
        value=plain(self.identity)
        value.update(promotion_scope='catalog_after_shared_broker_identity',
            identity_gate_path=self.requests.admission.identity_gate_path,
            identity_execution='controller_only',pending_withdrawal=True)
        self.identity=freeze(value)

    def _configuration(self):
        super()._configuration()
        if (not isinstance(self.requests.admission,BrokerManualAdmissionPolicy)
                or self.identity['identity_gate_path']!=self.requests.admission.identity_gate_path):
            raise ValueError('Manual shared identity binding changed')

    def _deny(self,cid,reason):
        self._append('result',cid,accepted=False,rejection_reason=reason,
            backend_sequence=None,backend_sha256=None)

    def _promotion_rejection(self,symbol):
        if symbol in self.requests.baseline.uni:return None
        proof=identity_proof(self.requests.admission)
        if proof['terminal_at'] is not None:return 'identity_provider_stop_required'
        return None if symbol in proof['approved_at'] else 'manual_identity_confirmation_required'

    def _admission_metadata(self,symbol):
        if symbol in self.requests.baseline.uni:return {}
        proof=identity_proof(self.requests.admission)
        return {'manual_identity_approvals':{symbol:proof['first_approval_sha256'][symbol]}}

    def _apply(self,requested,*,fault_hook=None):
        self._configuration()
        command,cid,now=requested['command'],requested['command_id'],self.now()
        _,commands,results=self._read()
        if command['action']=='withdraw':
            original=commands.get(command['request_id'])
            if (original is not None and original['command']['action']=='promote'
                    and original['command']['symbol'] not in self.requests.baseline.uni
                    and original['command_id'] not in results
                    and not any(e.kind=='request' and e.accepted and e.actor_id==self.actor_id
                        and e.command_id==original['command_id'] for e in self.requests.events())):
                self._deny(original['command_id'],'manual_withdrawn_before_admission')
                self._append('result',cid,accepted=True,rejection_reason=None,
                    backend_sequence=None,backend_sha256=None)
                return
        outside=(command['action']=='promote' and command['symbol'] not in self.requests.baseline.uni)
        if outside and session_start(self.requests.session_date)<=now<self.publication.settings.publish_until:
            if any(e.kind=='request'and e.actor_id==self.actor_id and e.command_id==cid for e in self.requests.events()):
                return super()._apply(requested,fault_hook=fault_hook)
            if command['symbol'] not in self.requests.admission.catalog_symbols:
                self._deny(cid,'symbol_not_in_admission_catalog');return
            events=self.requests.events()
            accepted={(e.actor_id,e.command_id):e.payload for e in events if e.kind=='request'and e.accepted}
            capacity=self.requests.admission.capacity_rejection(
                {'symbols':[command['symbol']],'sampling_channel':command['target']},
                baseline=self.requests.baseline,requests=accepted)
            if capacity is not None:self._deny(cid,capacity);return
            proof=identity_proof(self.requests.admission)
            code=proof['dispositions'].get(gate_command_id(cid))
            if code is not None and code!='approved':self._deny(cid,code);return
            if proof['terminal_at'] is not None:self._deny(cid,'identity_provider_stop_required');return
            if code is None:return # Requested is durable; no GUI provider dispatch.
        return super()._apply(requested,fault_hook=fault_hook)

    def snapshot(self):
        value=super().snapshot()
        outside=[r for r in value['commands']if r['action']=='promote'
            and r['symbol'] not in self.requests.baseline.uni]
        if not outside:return value
        proof=identity_proof(self.requests.admission)
        originals={r['command_id']:r for r in outside}
        for row in value['commands']:
            if row['action']=='withdraw'and row['request_id']in originals:
                row['symbol']=originals[row['request_id']]['symbol']
            if row in outside:
                code=proof['dispositions'].get(gate_command_id(row['command_id']))
                row['identity_status']=code or 'awaiting_broker_identity'
                if row['detail']=='manual_withdrawn_before_admission':
                    row.update(status='WITHDRAWN',detail='Own pending request withdrawn before admission.',publication_pending=False)
                elif row['status']=='REQUESTED':
                    if code is not None and code!='approved':
                        row.update(status='BLOCKED',detail=code,publication_pending=False)
                    else:
                        row.update(status='PENDING',detail='Identity confirmed; request delivery pending.'if code=='approved'else
                            'Awaiting exact broker identity confirmation; no membership admitted yet.',publication_pending=True)
        value['identity_quote_permits']=proof['quote_permits']
        value['maximum_identity_quote_permits']=120
        return value
