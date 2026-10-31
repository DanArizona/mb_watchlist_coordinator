"""Replayable manual admission backed by the original shared identity ledger.

The common request transaction reads retained broker decisions, never a provider.
Only decisions already present at the request's receipt time qualify it. Later
approvals/stops cannot retroactively change a stored admission disposition.
"""
from contextlib import closing
from collections.abc import Mapping
from dataclasses import dataclass,field
from pathlib import Path
import sqlite3
from types import SimpleNamespace

from .daily_shared_admission import SharedManualAdmissionPolicy
from .sampling_requests import canonical,digest,freeze,plain,timestamp

CONTRACT='daily-shared-nasdaq-manual-identity-gate-v1'


@dataclass(frozen=True,slots=True)
class BrokerManualAdmissionPolicy(SharedManualAdmissionPolicy):
    identity_gate_path:str=''
    _proof_cache:object=field(init=False,default=None,repr=False,compare=False)

    def _current_signature(self):
        return SharedManualAdmissionPolicy._current_signature(self)+((type(self.identity_gate_path),self.identity_gate_path),)

    def __post_init__(self):
        path=Path(self.identity_gate_path)
        if not self.identity_gate_path or not path.is_absolute() or path.name!='identity.sqlite3':
            raise ValueError('Original absolute shared identity ledger required')
        SharedManualAdmissionPolicy.__post_init__(self)
        value=plain(self._descriptor)
        value.update(contract='daily-broker-confirmed-manual-admission-v1',
            manual_promotion_scope='catalog_after_shared_broker_identity',identity_gate_path=str(path))
        object.__setattr__(self,'_descriptor',freeze(value))

    def capacity_rejection(self,payload,*,baseline,requests):
        self.payload()
        usage=self.capacity_summary(baseline=baseline,requests=(*requests.values(),payload))
        if usage['hot_distinct_used']>self.maximum_hot:return 'session_shared_hot_capacity'
        if usage['focus_additions_used']>self.maximum_focus_additions:return 'session_shared_focus_capacity'
        return None

    def identity_rejection(self,payload,*,baseline,at):
        if payload['producer_id']!=self.manual_actor_id or set(payload['symbols'])<=baseline.uni:return None
        proof=identity_proof(self)
        extra=set(payload['symbols'])-baseline.uni
        references=payload['metadata'].get('manual_identity_approvals',{})
        if not isinstance(references,Mapping) or set(references)!=extra or any(s not in proof['approved_at'] or proof['approved_at'][s]>at
                or references[s]!=proof['first_approval_sha256'][s] for s in extra):
            return 'manual_identity_confirmation_required'
        return None


def identity_proof(policy):
    """Validate raw proof without recursively reading requests/publication."""
    from .daily_multi_identity import MultiIdentityGate,MAX_CALLS,MAX_SYMBOLS,PER_SYMBOL_CALLS,CALL_INTERVAL
    from .controller_bootstrap import strict_json
    from .nasdaq_recovery import regular_window
    policy.payload()
    path=Path(policy.identity_gate_path)
    if not path.is_file() or path.is_symlink():raise ValueError('Original shared identity ledger missing')
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True))as c:
        c.execute('PRAGMA query_only=ON');c.execute('BEGIN')
        binding=c.execute('SELECT payload FROM identity_binding WHERE id=1').fetchone()
        rows=tuple(c.execute('SELECT sequence,payload FROM identity_event ORDER BY sequence'))
    key=(binding,rows)
    cached=policy._proof_cache
    if cached is not None and cached[0]==key:return cached[1]
    if binding is None:raise ValueError('Original shared identity binding missing')
    header=strict_json(binding[0]);start,stop=regular_window(timestamp(header['start_at_utc']).date())
    if (binding[0]!=canonical(header) or header['contract']!=CONTRACT
            or header['catalog_id']!=policy.catalog_id
            or header['gate_path']!=str(path.resolve())
            or header['request_admission_sha256']!=digest(policy.payload())
            or timestamp(header['start_at_utc'])!=start or timestamp(header['stop_at_utc'])!=stop
            or header['maximum_identity_quote_permits']!=MAX_CALLS
            or header['maximum_distinct_authorized_symbols']!=MAX_SYMBOLS
            or header['maximum_calls_per_symbol']!=PER_SYMBOL_CALLS
            or header['minimum_quote_interval_seconds']!=CALL_INTERVAL):
        raise ValueError('Shared broker identity proof binding differs')
    # Reuse the original pure decision and no-call rules, including exact
    # EQUITY/COE matching, status/timeout handling, budgets and reuse provenance.
    verifier=object.__new__(MultiIdentityGate)
    verifier.catalog=SimpleNamespace(symbols=policy.catalog_symbols)
    verifier.start,verifier.stop=start,stop
    previous,last,last_quote=digest(header),None,None
    reservations,decisions,selected,approved_at,approval_sha={},{},{},{},{}
    terminal_at=None
    for sequence,raw in rows:
        e=strict_json(raw);body=dict(e);sha=body.pop('event_sha256')
        at,cid=timestamp(e['at_utc']),e['command_id']
        if (raw!=canonical(e) or sequence!=len(reservations)+len(decisions)+1 or e['sequence']!=sequence
                or e['previous_sha256']!=previous or sha!=digest(body)
                or last is not None and at<last or terminal_at is not None):
            raise ValueError('Shared broker identity proof chain differs')
        if e['kind']=='reservation':
            code,_=verifier._no_call(e['symbol'],selected=selected,reservations=reservations,
                decisions=decisions,at=at,stopped=False)
            if cid in reservations or cid in decisions or code is not None or last_quote is not None and (at-last_quote).total_seconds()<CALL_INTERVAL:
                raise ValueError('Shared broker identity proof reservation differs')
            reservations[cid]=e;last_quote=at
        elif e['kind']=='decision':
            if cid in decisions:raise ValueError('Repeated shared identity decision')
            code=verifier._code(e,reservations=reservations,decisions=decisions,selected=selected,permits=len(reservations))
            if code!=e['code']:raise ValueError('Shared broker identity proof decision differs')
            if code=='approved':
                selected.setdefault(e['symbol'],cid);approved_at.setdefault(e['symbol'],at)
                approval_sha.setdefault(e['symbol'],sha)
            if code=='provider_stop_required':terminal_at=at
            decisions[cid]=e
        else:raise ValueError('Unknown shared broker identity proof event')
        previous,last=sha,at
    dispositions={cid:e['code']for cid,e in decisions.items()}
    dispositions.update({cid:'identity_outcome_unknown_no_retry'for cid in reservations if cid not in decisions})
    result=freeze({'approved_at':approved_at,'first_approval_sha256':approval_sha,
        'terminal_at':terminal_at,'dispositions':dispositions,'quote_permits':len(reservations)})
    object.__setattr__(policy,'_proof_cache',(key,result))
    return result
