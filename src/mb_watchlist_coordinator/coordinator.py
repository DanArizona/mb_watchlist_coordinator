from __future__ import annotations

from datetime import datetime

from .lifecycle import select_effective_intents
from .models import (
    CanonicalWatchlist,
    IntentCancellation,
    ProducerIntent,
)
from .policy import build_canonical_watchlist
from .state_store import AdapterStateStore


class WatchlistCoordinator:
    def __init__(self) -> None:
        self._intents: dict[str, ProducerIntent] = {}
        self._cancellations: dict[str, IntentCancellation] = {}
        self._revisions: list[CanonicalWatchlist] = []
        self._next_revision = 1
        self._adapter_state = AdapterStateStore()

    @property
    def current_canonical(self) -> CanonicalWatchlist | None:
        if not self._revisions:
            return None

        return self._revisions[-1]

    @property
    def revision_history(self) -> tuple[CanonicalWatchlist, ...]:
        return tuple(self._revisions)

    @property
    def adapter_state(self) -> AdapterStateStore:
        return self._adapter_state

    def accept_intent(
        self,
        intent: ProducerIntent,
        *,
        at: datetime,
    ) -> CanonicalWatchlist:
        if intent.intent_id in self._intents:
            raise ValueError(
                f"Duplicate intent_id: {intent.intent_id}"
            )

        self._intents[intent.intent_id] = intent

        return self.recompute(at=at)

    def accept_cancellation(
        self,
        cancellation: IntentCancellation,
        *,
        at: datetime,
    ) -> CanonicalWatchlist:
        if cancellation.cancellation_id in self._cancellations:
            raise ValueError(
                "Duplicate cancellation_id: "
                f"{cancellation.cancellation_id}"
            )

        if cancellation.intent_id not in self._intents:
            raise ValueError(
                "Cancellation references unknown intent_id: "
                f"{cancellation.intent_id}"
            )

        self._cancellations[
            cancellation.cancellation_id
        ] = cancellation

        return self.recompute(at=at)

    def recompute(
        self,
        *,
        at: datetime,
    ) -> CanonicalWatchlist:
        effective_intents = select_effective_intents(
            self._intents.values(),
            cancellations=self._cancellations.values(),
            at=at,
        )

        next_revision = self._next_revision

        candidate = build_canonical_watchlist(
            effective_intents,
            revision=next_revision,
            created_at=at,
        )

        current = self.current_canonical

        if (
            current is not None
            and candidate.symbols == current.symbols
            and candidate.input_intent_ids
            == current.input_intent_ids
            and candidate.policy_version
            == current.policy_version
        ):
            return current

        self._revisions.append(candidate)
        self._next_revision += 1

        return candidate
