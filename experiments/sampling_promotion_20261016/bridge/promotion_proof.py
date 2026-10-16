"""Synthetic membership proof using the real journal, audit, and replay APIs."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from mb_market_data.quote_event_state import QuoteEventStateProjector
from mb_market_data.quote_journal_audit import audit_quote_journal
from mb_market_data.quote_journal_replay import QuoteJournalReplayReader
from mb_market_data.quote_observation_store import QuoteObservationStore, RecordResult
from mb_market_data.sampling_membership import SamplingHierarchyRevision
from mb_watchlist_coordinator.models import IntentType, ProducerIntent
from sampling_journal_bridge import promotion_proposal, request_payload, utc_text


def plain(value):
    if isinstance(value, Mapping):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(v) for v in value]
    return value


def fixture():
    now = datetime.now(timezone.utc)
    # Real publication clocks, future planned membership; no sleeping or fake
    # backdating. Full replay immediately reconstructs these planned revisions.
    effective = (now + timedelta(minutes=10)).replace(second=0, microsecond=0)
    session = effective.astimezone(ZoneInfo("America/New_York")).date()
    baseline = SamplingHierarchyRevision(
        session_date=session, revision=0, effective_at=effective,
        uni_symbols=("AAPL", "MSFT", "SPY"), focus_symbols=("SPY",), hot_symbols=(),
        source="offline_synthetic_fixture", reason="Three-symbol test baseline",
        metadata={"experimental": True, "synthetic_membership": True},
    )
    request = ProducerIntent(
        intent_id="synthetic-promotion-001", producer_id="synthetic_halt_producer",
        intent_type=IntentType.ENSURE_PRESENT, symbols=frozenset({"MSFT"}),
        created_at=now, source_event_id="synthetic-event-001",
        reason="Synthetic event requests faster observation of MSFT",
        metadata={"sampling_channel": "hot", "session_date": session.isoformat(),
                  "synthetic": True},
    )
    return baseline, request, now


def replay_projection(database: Path) -> dict:
    projector = QuoteEventStateProjector()
    sequence = []
    checkpoints = []
    for event in QuoteJournalReplayReader(database).events():
        projector.apply(event)
        snap = projector.snapshot()
        sequence.append({"event_id": event.event_id,
                         "effective_at_utc": utc_text(event.available_at_utc),
                         "content_sha256": event.revision.content_sha256})
        checkpoints.append({"revision": event.revision.revision,
                            "membership": {c: list(snap.current_members(c))
                                           for c in ("uni", "focus", "hot")}})
    return {"sequence": sequence, "checkpoints": checkpoints,
            "sequence_sha256": hashlib.sha256(json.dumps(sequence, sort_keys=True).encode()).hexdigest()}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def run_proof(run_directory: Path) -> dict:
    database = run_directory / "synthetic_membership.sqlite3"
    if database.exists():
        raise ValueError("Proof requires a new journal")
    baseline, request, decided_at = fixture()
    store = QuoteObservationStore(database, session_date=baseline.session_date, schema_version=2)
    store.initialize()
    require(store.record_membership_revision(baseline) == RecordResult.INSERTED, "r0 insertion failed")
    # Build from the stored baseline so the same adapter can later consume an
    # authoritative committed revision. No poller or Coordinator daemon runs.
    committed_baseline = store.membership_revisions_in_effective_order()[0]
    decided_at = datetime.now(timezone.utc)
    proposal = promotion_proposal(committed_baseline, request, decided_at=decided_at,
                                  effective_at=baseline.effective_at + timedelta(seconds=1))
    require(store.record_membership_revision(proposal) == RecordResult.INSERTED, "r1 insertion failed")
    require(store.record_membership_revision(proposal) == RecordResult.ALREADY_PRESENT,
            "Retry was not idempotent")
    audit = audit_quote_journal(database)
    require(audit.passed, f"Journal audit failed: {audit.findings}")
    expected_counts = {"sampling_membership_revision": 2, "sampling_channel_revision": 6,
                       "sampling_channel_member": 10, "poll_run": 0,
                       "quote_acquisition": 0, "quote_observation": 0, "poll_slot_skip": 0}
    require(all(audit.table_counts[k] == n for k, n in expected_counts.items()), "Unexpected table counts")
    first, second = replay_projection(database), replay_projection(database)
    require(first == second, "Replay did not reproduce the same sequence and states")
    expected = [{"revision": 0, "membership": {"uni": ["AAPL", "MSFT", "SPY"],
                  "focus": ["SPY"], "hot": []}},
                {"revision": 1, "membership": {"uni": ["AAPL", "MSFT", "SPY"],
                  "focus": ["MSFT", "SPY"], "hot": ["MSFT"]}}]
    require(first["checkpoints"] == expected, "Replay membership differs from the promotion decision")
    revisions = store.membership_revisions_in_effective_order()
    require(plain(revisions[1].metadata["request"]) == request_payload(request), "Request provenance changed")
    for revision in revisions:
        require(revision.published_at is not None and revision.published_at <= revision.effective_at,
                "Publication time is missing or backdated")
    report = {
        "result": "PASS", "scope": "Offline synthetic membership only; no market acquisition or live transition",
        "session_date": baseline.session_date.isoformat(), "database": str(database.resolve()),
        "audit": "PASS", "table_counts": dict(audit.table_counts),
        "identical_replays": True, **first,
        "request": request_payload(request),
        "revisions": [{"revision": r.revision, "source": r.source, "reason": r.reason,
                       "effective_at_utc": utc_text(r.effective_at),
                       "published_at_utc": utc_text(r.published_at),
                       "content_sha256": r.content_sha256, "metadata": plain(r.metadata)} for r in revisions],
    }
    (run_directory / "proof_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (run_directory / "proof_report.txt").write_text(
        "Coordinator promotion proof: PASS\n"
        "Synthetic request: MSFT -> Hot\n"
        "r0: Uni=AAPL MSFT SPY; Focus=SPY; Hot=empty\n"
        "r1: Uni=AAPL MSFT SPY; Focus=MSFT SPY; Hot=MSFT\n"
        "Audit: PASS; two replays identical; retry idempotent\n"
        "No acquisitions. This is not a Hot poller or live Nasdaq integration.\n"
        f"Sequence SHA-256: {first['sequence_sha256']}\n", encoding="utf-8")
    return report
