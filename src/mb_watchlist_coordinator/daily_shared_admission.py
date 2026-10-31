"""Shared Nasdaq/manual session capacity, checked inside the request transaction.

Distinct Hot and Focus additions remain charged after withdrawal/restriction.
This bounds both current membership (including stabilization holds) and later
re-admission without maintaining a resettable second capacity ledger.
"""
from dataclasses import dataclass
from .daily_admission import DailyAdmissionPolicy
from .sampling_requests import freeze, plain


@dataclass(frozen=True, slots=True)
class SharedManualAdmissionPolicy(DailyAdmissionPolicy):
    manual_actor_id: str = 'operator:masterbot'
    maximum_hot: int = 40
    maximum_focus_additions: int = 40

    def _current_signature(self):
        return DailyAdmissionPolicy._current_signature(self)+tuple(
            (type(v),v) for v in (self.manual_actor_id,self.maximum_hot,self.maximum_focus_additions))

    def __post_init__(self):
        if (self.manual_actor_id != 'operator:masterbot' or type(self.maximum_hot) is not int
                or type(self.maximum_focus_additions) is not int
                or self.maximum_hot != 40 or self.maximum_focus_additions != 40
                or self.manual_actor_id not in self.allowed_sources):
            raise ValueError('Explicit sealed shared manual capacity required')
        DailyAdmissionPolicy.__post_init__(self)
        value=plain(self._descriptor)
        value.update(contract='daily-shared-nasdaq-manual-admission-v1',
            manual_actor_id=self.manual_actor_id,manual_promotion_scope='opening_uni_only',
            maximum_distinct_hot_symbols_per_session=self.maximum_hot,
            maximum_distinct_focus_additions_per_session=self.maximum_focus_additions,
            capacity_lifetime='session_nonrecycling_includes_withdrawn_and_restricted_requests')
        object.__setattr__(self,'_descriptor',freeze(value))

    def capacity_rejection(self, payload, *, baseline, requests):
        self.payload()  # Recheck all immutable fields before accepting/replaying.
        if payload['producer_id']==self.manual_actor_id and not set(payload['symbols'])<=baseline.uni:
            return 'manual_identity_confirmation_required'
        usage=self.capacity_summary(baseline=baseline,requests=(*requests.values(),payload))
        if usage['hot_distinct_used']>self.maximum_hot: return 'session_shared_hot_capacity'
        if usage['focus_additions_used']>self.maximum_focus_additions:
            return 'session_shared_focus_capacity'
        return None

    def capacity_summary(self, *, baseline, requests):
        self.payload()
        hot=set(baseline.hot); focus=set(baseline.focus)
        for request in requests:
            if request['sampling_channel']=='hot': hot.update(request['symbols'])
            if request['sampling_channel'] in ('hot','focus'): focus.update(request['symbols'])
        return {'hot_distinct_used':len(hot),'hot_limit':self.maximum_hot,
            'focus_additions_used':len(focus-set(baseline.focus)),
            'focus_additions_limit':self.maximum_focus_additions,
            'hot_remaining':max(0,self.maximum_hot-len(hot)),'budget_lifetime':'session_nonrecycling'}
