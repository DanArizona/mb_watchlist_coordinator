"""Synthetic future policy clock; actual SQLite publication timestamps.

The injected policy clock advances instantly. Its receipts are simulation
evidence, not wall-clock acquisition timestamps. Every journal revision retains
that distinction. No production policy defaults or live cadence are selected.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from mb_market_data.quote_journal_audit import audit_quote_journal
from mb_market_data.quote_observation_store import QuoteObservationStore, RecordResult
from mb_market_data.sampling_membership import SamplingHierarchyRevision
from mb_watchlist_coordinator.models import IntentType, ProducerIntent
from mb_watchlist_coordinator.sampling_policy import SamplingPolicy
from mb_watchlist_coordinator.sampling_projection import SamplingMembership
from mb_watchlist_coordinator.sampling_request_store import SamplingRequestStore
from mb_watchlist_coordinator.sampling_requests import baseline_payload, digest, membership_payload, plain
from request_proof import journal_replay, require


PROOF_POLICY = SamplingPolicy("proof-super-user", 60, 120, "immediate_cap")
SOURCE = "synthetic_policy_clock_fixture"


class PolicyClock:
    def __init__(self):
        # A logical daytime fixture remains valid near actual ET midnight.
        self.start = (datetime.now(ZoneInfo("America/New_York")) + timedelta(days=1)).replace(
            hour=10, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
        self.value = self.start

    def at(self, seconds):
        self.value = self.start + timedelta(seconds=seconds)

    def __call__(self):
        return self.value


def initialize_fixture(folder: Path):
    clock = PolicyClock()
    session = clock.start.astimezone(ZoneInfo("America/New_York")).date()
    require((clock.start + timedelta(seconds=300)).astimezone(ZoneInfo("America/New_York")).date() == session,
            "Run this synthetic policy proof away from ET midnight")
    baseline = SamplingMembership(frozenset({"AAPL", "MSFT", "SPY"}), frozenset({"SPY"}), frozenset())
    ledger = SamplingRequestStore(folder / "policy_requests.sqlite3", session_date=session,
        baseline=baseline, clock=clock, policy=PROOF_POLICY)
    ledger.initialize()
    journal = QuoteObservationStore(folder / "policy_membership.sqlite3", session_date=session, schema_version=2)
    journal.initialize()
    journal.record_membership_revision(SamplingHierarchyRevision(
        session_date=session, revision=0, effective_at=clock.start - timedelta(seconds=1),
        uni_symbols=tuple(baseline.uni), focus_symbols=tuple(baseline.focus), hot_symbols=(),
        source=SOURCE, reason="Synthetic policy baseline; proof-only settings",
        metadata={"experimental": True, "synthetic_policy_clock": True,
                  "request_baseline_sha256": digest(baseline_payload(session, baseline, PROOF_POLICY)),
                  "policy": PROOF_POLICY.payload()},
    ))
    return ledger, journal, clock


def publish_policy_states(ledger, journal):
    states = ledger.states()
    events = ledger.events()
    revisions = journal.membership_revisions_in_effective_order()
    opening = revisions[0]
    require(opening.source == SOURCE and opening.metadata["synthetic_policy_clock"] is True,
            "Unexpected policy proof identity")
    require(opening.metadata["request_baseline_sha256"] == states[0].event_sha256,
            "Policy ledger and journal baseline differ")
    require(len(revisions) <= len(states), "Published history is ahead of the policy ledger")
    previous_effective = opening.effective_at
    proposals = []
    for state, event in zip(states[1:], events):
        require(opening.published_at <= state.as_of, "Synthetic knowledge precedes baseline publication")
        effective = max(previous_effective + timedelta(microseconds=1), state.as_of + timedelta(microseconds=1))
        for restriction in state.active_restrictions:
            require(datetime.fromisoformat(restriction["expires_at_utc"]) > effective,
                    "Restriction expires before scheduled publication")
        for request in state.active_requests:
            require(request["expires_at_utc"] is None or datetime.fromisoformat(request["expires_at_utc"]) > effective,
                    "Request expires before scheduled publication")
        proposals.append(SamplingHierarchyRevision(
            session_date=ledger.session_date, revision=state.sequence, effective_at=effective,
            uni_symbols=tuple(state.applied.uni), focus_symbols=tuple(state.applied.focus),
            hot_symbols=tuple(state.applied.hot), source="experimental_policy_reducer",
            reason=f"Synthetic policy receipt {state.sequence}: {event.kind}",
            metadata={"experimental": True, "synthetic_policy_clock": True,
                      "request_state": state.payload(), "input_event": event.hash_payload(),
                      "request_event_sha256": event.event_sha256,
                      "request_baseline_sha256": states[0].event_sha256},
        ))
        previous_effective = effective
    for previous, candidate in zip(revisions[1:], proposals):
        require(previous.content_sha256 == candidate.content_sha256, "Published policy prefix differs from replay")
    return tuple(journal.record_membership_revision(p) for p in proposals)


def run_proof(folder: Path):
    require(not any(folder.glob("*.sqlite3")), "A fresh directory is required")
    ledger, journal, clock = initialize_fixture(folder)
    trace = []

    def record(label, seconds, action):
        clock.at(seconds)
        result = action()
        state = ledger.states()[-1]
        trace.append({"label": label, "synthetic_seconds": seconds,
                      "accepted": result.event.accepted, "state": state.payload()})
        return state

    def request(owner, rid):
        intent = ProducerIntent(rid, owner, IntentType.ENSURE_PRESENT, frozenset({"MSFT"}), clock(),
            source_event_id="synthetic-" + rid, reason="Synthetic policy test request",
            metadata={"sampling_channel": "hot", "session_date": ledger.session_date.isoformat(), "synthetic_policy_clock": True})
        return ledger.submit_request(intent, actor_id=owner)

    def restrict(rid, cap, expiry, actor="proof-super-user"):
        return ledger.restrict_symbol(rid, symbol="MSFT", max_group=cap, actor_id=actor,
            expires_at=clock.start + timedelta(seconds=expiry) if expiry is not None else None,
            reason="Synthetic restriction")

    def clear(rid, cid):
        return ledger.clear_restriction(cid, symbol="MSFT", restriction_id=rid, actor_id="proof-super-user")

    def restart():
        nonlocal ledger
        original = tuple(s.payload() for s in ledger.states())
        ledger = SamplingRequestStore(ledger.path, session_date=ledger.session_date, baseline=ledger.baseline,
                                      policy=PROOF_POLICY, clock=clock)
        require(tuple(s.payload() for s in ledger.states()) == original, "Restart changed policy state or timers")

    record("fast promotion", 0, lambda: request("manual", "m1"))
    record("ordinary withdrawal starts hold", 10, lambda: ledger.cancel_request("c1", owner_id="manual", request_id="m1", actor_id="manual"))
    require(record("before residence deadline", 119, lambda: ledger.tick("early")).applied.hot == {"MSFT"}, "Early ordinary demotion")
    restart()
    require(record("ordinary demotion at deadline", 120, lambda: ledger.tick("due")).applied == ledger.baseline, "Ordinary demotion did not occur")
    record("halt promotion", 121, lambda: request("halts", "h1"))
    denied = record("foreign restriction rejected", 122, lambda: restrict("denied", "uni", 300, "manual"))
    require(denied.rejected_count == 1 and not trace[-1]["accepted"], "Foreign authority was accepted")
    require(record("immediate Focus cap", 123, lambda: restrict("r1", "focus", 180)).applied.hot == frozenset(), "Cap waited for ordinary dwell")
    record("demand retained under cap", 124, lambda: request("manual", "m2"))
    require(record("replacement Uni cap", 125, lambda: restrict("r2", "uni", 170)).applied == ledger.baseline, "Uni cap did not constrain membership")
    stale = record("stale clear rejected", 126, lambda: clear("r1", "stale"))
    require(stale.active_restrictions[0]["restriction_id"] == "r2", "Stale clear removed replacement")
    reentry = record("replacement expires without old revival", 170, lambda: ledger.tick("cap-expiry"))
    require(reentry.applied.hot == {"MSFT"} and not reentry.active_restrictions, "Expiry revived old cap or lost active demand")
    record("new Uni cap", 171, lambda: restrict("r3", "uni", 300))
    record("withdraw halt under cap", 172, lambda: ledger.cancel_request("h-cancel", owner_id="halts", request_id="h1", actor_id="halts"))
    record("withdraw manual under cap", 173, lambda: ledger.cancel_request("m2-cancel", owner_id="manual", request_id="m2", actor_id="manual"))
    require(record("clear does not restore stale demand", 174, lambda: clear("r3", "clear-r3")).applied == ledger.baseline, "Clear blindly restored prior membership")
    record("fresh manual promotion", 175, lambda: request("manual", "m3"))
    cap = record("session-bounded cap", 176, lambda: restrict("r4", "focus", None))
    expiry = cap.active_restrictions[0]["expires_at_utc"]
    restart()
    require(ledger.states()[-1].active_restrictions[0]["expires_at_utc"] == expiry, "Restart extended restriction expiry")
    record("clear reevaluates current demand", 177, lambda: clear("r4", "clear-r4"))
    record("last withdrawal after reentry", 178, lambda: ledger.cancel_request("m3-cancel", owner_id="manual", request_id="m3", actor_id="manual"))
    require(record("new residence deadline held", 296, lambda: ledger.tick("reentry-early")).applied.hot == {"MSFT"}, "Reentry reused an old residence timer")
    require(record("new residence deadline reached", 297, lambda: ledger.tick("reentry-due")).applied == ledger.baseline, "Final ordinary demotion failed")
    restart()
    first = publish_policy_states(ledger, journal)
    require(all(x == RecordResult.INSERTED for x in first), "Initial policy publication was not inserted")
    require(all(x == RecordResult.ALREADY_PRESENT for x in publish_policy_states(ledger, journal)), "Policy publication retry changed content")
    a, b = journal_replay(journal.database_path), journal_replay(journal.database_path)
    require(a == b, "Policy journal replays differ")
    states = ledger.states()
    require(len(a) == len(states), "Policy checkpoint count differs")
    for state, checkpoint in zip(states, a):
        require(checkpoint["membership"] == membership_payload(state.applied), "Policy publication differs from request reducer")
    audit = audit_quote_journal(journal.database_path)
    require(audit.passed, f"Policy journal audit failed: {audit.findings}")
    require(audit.table_counts["quote_acquisition"] == 0, "Unexpected market acquisition")
    report = {"result": "PASS", "synthetic_policy_clock": True,
              "clock_description": "Injected future logical time; journal published_at uses the real clock",
              "policy_settings": PROOF_POLICY.payload(), "settings_status": "proof_only_no_production_defaults",
              "trace": trace, "request_checkpoints": [s.payload() for s in states],
              "request_events": [dict(e.hash_payload(), event_sha256=e.event_sha256) for e in ledger.events()],
              "journal_checkpoints": a, "audit": "PASS", "table_counts": dict(audit.table_counts),
              "request_replay_sha256": digest([s.payload() for s in states]), "journal_replay_sha256": digest(a),
              "journal_publication_times": [r.published_at.isoformat() for r in journal.membership_revisions_in_effective_order()]}
    (folder / "proof_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    summary = "\n".join([
        "Restriction and demotion policy proof: PASS",
        "Clock: synthetic logical time; SQLite publication timestamps are real",
        "Proof settings: grace=60s; minimum residence=120s; immediate restriction cap",
        "Settings are test configuration; no production defaults selected",
        "Fast promotions and ordinary delayed demotions: PASS",
        "One authority; foreign and stale controls rejected: PASS",
        "Clear/expiry reevaluate demand; superseded restrictions stay superseded: PASS",
        "Restart preserves deadlines and timers; reentry resets residence: PASS",
        "Journal audit: PASS; two replays identical; retry idempotent",
        f"Receipts: {len(trace)}; hierarchy revisions: {len(a)}; market acquisitions: 0",
        f"Request replay SHA-256: {report['request_replay_sha256']}",
        f"Journal replay SHA-256: {report['journal_replay_sha256']}", "",
    ])
    (folder / "proof_report.txt").write_text(summary, encoding="utf-8")
    return report
