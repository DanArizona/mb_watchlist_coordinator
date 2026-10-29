"""Daily admission with an exact catalog digest instead of copied symbol lists.

The full eligibility set remains in the immutable policy and retained catalog.
Only its repeated identity serialization is compact; admission rules are the
ordinary implementation. Existing experiment identities remain unchanged.
"""
from dataclasses import dataclass,field
from .sampling_admission import AdmissionPolicy
from .sampling_requests import digest,freeze,plain


@dataclass(frozen=True,slots=True)
class DailyAdmissionPolicy(AdmissionPolicy):
    _signature:tuple=field(init=False,repr=False,compare=False)
    _descriptor:object=field(init=False,repr=False,compare=False)

    def _current_signature(self):
        values=(self.catalog_id,self.catalog_symbols,self.allowed_sources,self.max_additional_symbols,self.uni_retention)
        return tuple((type(v),v) for v in values)

    def __post_init__(self):
        AdmissionPolicy.__post_init__(self)
        object.__setattr__(self,'_signature',self._current_signature())
        descriptor={'contract':'daily-admission-catalog-digest-v1','catalog_id':self.catalog_id,
            'catalog_symbols_sha256':digest(sorted(self.catalog_symbols)),
            'catalog_symbol_count':len(self.catalog_symbols),'allowed_sources':sorted(self.allowed_sources),
            'max_additional_symbols':self.max_additional_symbols,'uni_retention':self.uni_retention,
            'capacity':'admitted_plus_uncancelled_unexpired_reservations',
            'catalog_scope':'identity_eligibility_not_daily_screen_or_broker_tradability'}
        object.__setattr__(self,'_descriptor',freeze(descriptor))

    def payload(self):
        if self._current_signature()!=self._signature:
            raise ValueError('Daily admission policy changed after construction')
        return plain(self._descriptor)
