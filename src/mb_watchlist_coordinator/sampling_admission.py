"""Explicit, session-bound admission settings; no network or daily screen.

The catalog is an instrument-identity eligibility input, not a sampling roster.
Its provenance and symbols are pinned in the request ledger. Production catalog
acquisition and broker symbol resolution are outside this offline increment.
"""

from __future__ import annotations

from dataclasses import dataclass

from .sampling_projection import SamplingMembership


@dataclass(frozen=True, slots=True)
class AdmissionPolicy:
    catalog_id: str
    catalog_symbols: frozenset[str]
    allowed_sources: frozenset[str]
    max_additional_symbols: int
    uni_retention: str

    def __post_init__(self):
        if (not isinstance(self.catalog_id, str) or not self.catalog_id.strip()
                or self.catalog_id != self.catalog_id.strip()):
            raise ValueError("Admission requires an explicit catalog identity")
        if isinstance(self.catalog_symbols, str) or isinstance(self.allowed_sources, str):
            raise ValueError("Catalog and sources must be collections")
        symbols = SamplingMembership(self.catalog_symbols, frozenset(), frozenset()).uni
        sources = frozenset(self.allowed_sources)
        if not sources or any(not isinstance(s, str) or not s.strip() or s != s.strip()
                              or s == "__coordinator__" for s in sources):
            raise ValueError("Admission requires explicit permitted source identities")
        if type(self.max_additional_symbols) is not int or self.max_additional_symbols < 0:
            raise ValueError("max_additional_symbols must be an explicit nonnegative integer")
        if self.uni_retention != "session":
            raise ValueError("Select uni_retention='session' explicitly")
        object.__setattr__(self, "catalog_symbols", symbols)
        object.__setattr__(self, "allowed_sources", sources)

    def payload(self):
        return {"catalog_id": self.catalog_id, "catalog_symbols": sorted(self.catalog_symbols),
                "allowed_sources": sorted(self.allowed_sources),
                "max_additional_symbols": self.max_additional_symbols,
                "uni_retention": self.uni_retention,
                "capacity": "admitted_plus_uncancelled_unexpired_reservations",
                "catalog_scope": "identity_eligibility_not_daily_screen_or_broker_tradability"}
