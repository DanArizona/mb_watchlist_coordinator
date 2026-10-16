"""Offline planned-publication proof, not a live Coordinator publication loop."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from mb_market_data.quote_event_state import QuoteEventStateProjector
from mb_market_data.quote_journal_audit import audit_quote_journal
from mb_market_data.quote_journal_replay import QuoteJournalReplayReader
from mb_market_data.quote_observation_store import QuoteObservationStore, RecordResult
from mb_market_data.sampling_membership import SamplingHierarchyRevision
from mb_watchlist_coordinator.models import IntentType, ProducerIntent
from mb_watchlist_coordinator.sampling_projection import SamplingMembership
from mb_watchlist_coordinator.sampling_request_store import SamplingRequestStore
from mb_watchlist_coordinator.sampling_requests import (
    baseline_payload, digest, membership_payload, plain, utc_text,
)


FIXTURE_SOURCE = "synthetic_source_owned_requests"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def initialize_fixture(folder: Path):
    now = datetime.now(timezone.utc)
    effective = (now + timedelta(minutes=10)).replace(second=0, microsecond=0)
    session = effective.astimezone(ZoneInfo("America/New_York")).date()
    require(now.astimezone(ZoneInfo("America/New_York")).date() == session,
            "Run this planned-publication proof away from ET midnight")
    baseline = SamplingMembership(frozenset({"AAPL", "MSFT", "SPY"}), frozenset({"SPY"}), frozenset())
    ledger = SamplingRequestStore(folder / "request_ledger.sqlite3", session_date=session, baseline=baseline)
    ledger.initialize()
    journal = QuoteObservationStore(folder / "membership.sqlite3", session_date=session, schema_version=2)
    journal.initialize()
    opening = SamplingHierarchyRevision(
        session_date=session, revision=0, effective_at=effective,
        uni_symbols=tuple(baseline.uni), focus_symbols=tuple(baseline.focus), hot_symbols=(),
        source=FIXTURE_SOURCE, reason="Synthetic fixed-Uni request lifecycle baseline",
        metadata={"experimental": True, "request_baseline_sha256": digest(baseline_payload(session, baseline))},
    )
    journal.record_membership_revision(opening)
    return ledger, journal


def synthetic_request(ledger, owner, request_id, **kwargs):
    payload = dict(intent_id=request_id, producer_id=owner, intent_type=IntentType.ENSURE_PRESENT,
                   symbols=frozenset({"MSFT"}), created_at=datetime.now(timezone.utc),
                   source_event_id="synthetic-" + request_id, reason="Synthetic request from " + owner,
                   metadata={"sampling_channel": "hot", "session_date": ledger.session_date.isoformat()})
    payload.update(kwargs)
    return ProducerIntent(**payload)


def publish_recorded_states(ledger, journal):
    """Replay a fixed future fixture schedule; identical retries preserve receipts.

    Every logged event gets a complete revision, including retained rejected
    input evidence. This is a deterministic offline publication policy. Live
    scheduling, an outbox and publication acknowledgements are future work.
    """
    states = ledger.states()
    events = ledger.events()
    revisions = journal.membership_revisions_in_effective_order()
    require(revisions and revisions[0].source == FIXTURE_SOURCE, "Unexpected journal fixture identity")
    opening = revisions[0]
    require(opening.metadata["request_baseline_sha256"] == states[0].event_sha256,
            "Journal and request ledger baselines differ")
    require(membership_payload(ledger.baseline) == {c: list(opening.symbols_for(c)) for c in ("uni", "focus", "hot")},
            "Journal and request ledger memberships differ")
    require(len(revisions) <= len(states), "Published history is ahead of request ledger")
    proposals = []
    for state, event in zip(states[1:], events):
        effective = opening.effective_at + timedelta(seconds=state.sequence)
        require(opening.published_at <= state.as_of <= effective,
                "Recorded knowledge cannot precede baseline publication or follow scheduled effect")
        for r in state.active_requests:
            expiry = r["expires_at_utc"]
            require(expiry is None or datetime.fromisoformat(expiry) > effective,
                    "Active request expires before the fixture's scheduled effect")
        proposals.append(SamplingHierarchyRevision(
            session_date=ledger.session_date, revision=state.sequence, effective_at=effective,
            uni_symbols=tuple(state.retained.uni), focus_symbols=tuple(state.retained.focus),
            hot_symbols=tuple(state.retained.hot), source="experimental_request_reducer",
            reason=f"Request event {state.sequence}: {event.kind}; " + ("accepted" if event.accepted else "rejected"),
            metadata={"experimental": True, "request_state": state.payload(),
                      "input_event": event.hash_payload(), "request_event_sha256": event.event_sha256,
                      "request_baseline_sha256": states[0].event_sha256},
        ))
    # Validate the already-published prefix before extending it.
    for old, proposal in zip(revisions[1:], proposals):
        require(old.content_sha256 == proposal.content_sha256,
                "Published revision differs from request replay")
    return tuple(journal.record_membership_revision(p) for p in proposals)


def journal_replay(path):
    projector = QuoteEventStateProjector()
    checkpoints = []
    for event in QuoteJournalReplayReader(path).events():
        projector.apply(event)
        state = projector.snapshot()
        checkpoints.append({"revision": event.revision.revision,
                            "content_sha256": event.revision.content_sha256,
                            "membership": {c: list(state.current_members(c)) for c in ("uni", "focus", "hot")},
                            "metadata": plain(event.revision.metadata)})
    return checkpoints


def run_proof(folder: Path):
    require(not any(folder.glob("*.sqlite3")), "A fresh run directory is required")
    ledger, journal = initialize_fixture(folder)
    manual = synthetic_request(ledger, "manual", "keep-msft")
    halt = synthetic_request(ledger, "halts", "halt-001")
    ledger.submit_request(manual, actor_id="manual")
    require(publish_recorded_states(ledger, journal) == (RecordResult.INSERTED,), "Manual promotion not published")
    ledger.submit_request(halt, actor_id="halts")
    before_restart = tuple(s.payload() for s in ledger.states())
    # Simulate restart after durable input but before its publication.
    ledger = SamplingRequestStore(ledger.path, session_date=ledger.session_date, baseline=ledger.baseline)
    require(tuple(s.payload() for s in ledger.states()) == before_restart, "Restart changed request state")
    require(publish_recorded_states(ledger, journal) == (RecordResult.ALREADY_PRESENT, RecordResult.INSERTED),
            "Restart did not reconcile pending input idempotently")
    ledger.cancel_request("withdraw-manual", owner_id="manual", request_id="keep-msft", actor_id="manual")
    require(ledger.states()[-1].reasons_for("MSFT", "hot") == (("halts", "halt-001"),),
            "Manual withdrawal lost the halt request")
    denied = ledger.cancel_request("foreign-withdrawal", owner_id="halts", request_id="halt-001", actor_id="manual")
    require(not denied.event.accepted, "Foreign cancellation was accepted")
    require(ledger.states()[-1].desired.hot == {"MSFT"}, "Foreign cancellation changed membership")
    ledger.cancel_request("withdraw-halt", owner_id="halts", request_id="halt-001", actor_id="halts")
    require(not ledger.submit_request(manual, actor_id="manual").inserted, "Duplicate request was appended")
    require(not ledger.cancel_request("withdraw-halt", owner_id="halts", request_id="halt-001", actor_id="halts").inserted,
            "Duplicate cancellation was appended")
    publish_recorded_states(ledger, journal)
    # Simulate restart after journal commit without a publisher acknowledgement.
    reopened = SamplingRequestStore(ledger.path, session_date=ledger.session_date, baseline=ledger.baseline)
    require(all(x == RecordResult.ALREADY_PRESENT for x in publish_recorded_states(reopened, journal)),
            "Published retry was not idempotent")
    first, second = journal_replay(journal.database_path), journal_replay(journal.database_path)
    require(first == second, "Journal replay changed")
    states = reopened.states()
    require(len(states) == 6 and len(first) == 6, "Expected five receipts and six hierarchy snapshots")
    for state, checkpoint in zip(states, first):
        require(membership_payload(state.retained) == checkpoint["membership"], "Journal membership differs from reducer")
    require(tuple(s.payload() for s in states) == tuple(s.payload() for s in ledger.states()), "Request replay changed")
    final = states[-1]
    require(final.desired.hot == frozenset() and final.retained.hot == {"MSFT"}, "Demotion policy boundary was lost")
    require(final.demotion_eligible_hot == ("MSFT",) and final.rejected_count == 1, "Unexpected final eligibility or rejection count")
    audit = audit_quote_journal(journal.database_path)
    require(audit.passed, f"Journal audit failed: {audit.findings}")
    counts = {"sampling_membership_revision": 6, "sampling_channel_revision": 18,
              "sampling_channel_member": 34, "quote_acquisition": 0, "quote_observation": 0, "poll_run": 0}
    require(all(audit.table_counts[k] == v for k, v in counts.items()), "Unexpected journal counts")
    report = {"result": "PASS", "scope": "Synthetic request lifecycle and planned publication; zero market acquisitions",
              "request_events": [dict(e.hash_payload(), event_sha256=e.event_sha256) for e in reopened.events()],
              "request_checkpoints": [s.payload() for s in states], "journal_checkpoints": first,
              "journal_audit": "PASS", "table_counts": dict(audit.table_counts),
              "request_restart_identical": True, "two_journal_replays_identical": True,
              "journal_retry_idempotent": True, "request_replay_sha256": digest([s.payload() for s in states]),
              "journal_replay_sha256": digest(first)}
    (folder / "proof_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    summary = "\n".join([
        "Source-owned request proof: PASS", "Manual request: MSFT -> Hot and Focus",
        "Halt request: both sources retained", "Manual withdrawal: MSFT stays Hot for halt request",
        "Foreign withdrawal: rejected and retained in request history",
        "Last withdrawal: MSFT eligible for demotion; membership retained pending policy",
        "Request restart/replay: identical; publication retry: idempotent",
        "Journal audit: PASS; two journal replays: identical",
        "Receipts: 5; hierarchy revisions: 6; market acquisitions: 0",
        f"Request replay SHA-256: {report['request_replay_sha256']}",
        f"Journal replay SHA-256: {report['journal_replay_sha256']}", "",
    ])
    (folder / "proof_report.txt").write_text(summary, encoding="utf-8")
    return report
