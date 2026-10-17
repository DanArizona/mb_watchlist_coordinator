"""Optional schema-v2 journal bridge; importing the Coordinator needs no MD install."""

from __future__ import annotations

from datetime import date

from .sampling_requests import freeze, plain, timestamp, utc_text


class PublicationDeadlineMissed(RuntimeError):
    """Store rejected a proposal whose effective time passed before insertion."""


class SamplingJournal:
    def __init__(self, store):
        # The caller explicitly supplies its pinned/installed market-data store.
        from mb_market_data.sampling_membership import SamplingHierarchyRevision
        if store.schema_version != 2:
            raise ValueError("Sampling publication requires a schema-v2 journal")
        self.store = store
        self.revision_type = SamplingHierarchyRevision
        self.identity = freeze({"path": str(store.database_path.resolve()),
                               "session_date": store.session_date.isoformat(), "schema_version": 2})

    def _check(self):
        if (str(self.store.database_path.resolve()) != self.identity["path"] or
                self.store.session_date.isoformat() != self.identity["session_date"] or self.store.schema_version != 2):
            raise ValueError("Sampling journal bridge configuration changed")

    def value(self, payload):
        return self.revision_type(
            session_date=date.fromisoformat(payload["session_date"]),
            revision=payload["revision"], effective_at=timestamp(payload["effective_at_utc"]),
            uni_symbols=tuple(payload["uni_symbols"]), focus_symbols=tuple(payload["focus_symbols"]),
            hot_symbols=tuple(payload["hot_symbols"]), source=payload["source"],
            reason=payload["reason"], metadata=plain(payload["metadata"]))

    def content_hash(self, payload):
        return self.value(payload).content_sha256

    def revisions(self):
        self._check()
        result = []
        for value in self.store.membership_revisions_in_effective_order():
            payload = {"session_date": value.session_date.isoformat(), "revision": value.revision,
                       "effective_at_utc": utc_text(value.effective_at),
                       "uni_symbols": list(value.uni_symbols), "focus_symbols": list(value.focus_symbols),
                       "hot_symbols": list(value.hot_symbols), "source": value.source,
                       "reason": value.reason, "metadata": plain(value.metadata)}
            if self.content_hash(payload) != value.content_sha256:
                raise ValueError("Journal content hash differs from reconstructed hierarchy")
            result.append({"proposal": payload, "content_sha256": value.content_sha256,
                           "published_at_utc": utc_text(value.published_at)})
        return result

    def publish(self, payload):
        from mb_market_data.sampling_membership import MembershipRevisionError
        self._check()
        try:
            self.store.record_membership_revision(self.value(payload))
        except MembershipRevisionError as exc:
            if str(exc) == "effective_at cannot precede published_at":
                raise PublicationDeadlineMissed(str(exc)) from exc
            raise
