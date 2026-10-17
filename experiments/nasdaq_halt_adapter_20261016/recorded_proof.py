"""Original recorded feed inspection plus a separately labeled arrival simulation."""
from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as XML
from collections import Counter
from dataclasses import asdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from nasdaq_halts import normalize_nasdaq_xml, parse_records
from mb_market_data.quote_journal_audit import audit_quote_journal
from mb_market_data.quote_observation_store import QuoteObservationStore, RecordResult
from mb_market_data.sampling_membership import SamplingHierarchyRevision
from mb_watchlist_coordinator.models import IntentType, ProducerIntent
from mb_watchlist_coordinator.nasdaq_sampling import (
    HaltProducerSettings, HaltSnapshot, NasdaqSamplingProducer, halt_event_id,
)
from mb_watchlist_coordinator.sampling_policy import SamplingPolicy
from mb_watchlist_coordinator.sampling_projection import SamplingMembership
from mb_watchlist_coordinator.sampling_request_store import SamplingRequestStore
from mb_watchlist_coordinator.sampling_requests import digest, membership_payload, plain
from request_proof import journal_replay, require

ET = ZoneInfo("America/New_York")
EXPERIMENT = Path(__file__).resolve().parent
SOURCE = "recorded_nasdaq_derived_arrival_simulation"
PROOF_POLICY = SamplingPolicy("proof-super-user", 60, 120, "immediate_cap")


def verify_evidence(folder=EXPERIMENT / "evidence", manifest=None):
    manifest = manifest or json.loads((EXPERIMENT / "evidence_manifest.json").read_text())
    for relative, expected in manifest["files"].items():
        path = (folder / relative).resolve()
        require(path.is_relative_to(folder.resolve()), "Evidence path escapes its directory")
        require(path.is_file(), "Missing evidence: " + relative)
        data = path.read_bytes()
        require(len(data) == expected["size"] and hashlib.sha256(data).hexdigest() == expected["sha256"],
                "Recorded evidence changed: " + relative)
    return manifest


def parse_saved(raw, *, capture_id, retrieved_at, mode, provenance):
    root = XML.fromstring(normalize_nasdaq_xml(raw))
    require(root.tag == "rss" and root.find("channel") is not None,
            "Expected a complete RSS channel, not an arbitrary empty XML document")
    records = parse_records(raw, retrieved_at_et=retrieved_at, retrieval_mode=mode)
    return HaltSnapshot(capture_id, retrieved_at, mode, hashlib.sha256(raw).hexdigest(),
                        tuple(asdict(r) for r in records), provenance)


def load_captures(folder=EXPERIMENT / "evidence"):
    manifest = verify_evidence(folder)
    captures, report = [], []
    for relative in sorted(n for n in manifest["files"] if n.endswith("normalized.json")):
        legacy = json.loads((folder / relative).read_text())
        times = {r["retrieved_at_et"] for r in legacy}
        modes = {r["retrieval_mode"] for r in legacy}
        require(len(times) == len(modes) == 1, "Capture has ambiguous original receipt metadata")
        capture_id = str(Path(relative).parent.as_posix())
        raw = (folder / capture_id / "raw.xml").read_bytes()
        snap = parse_saved(raw, capture_id=capture_id, retrieved_at=datetime.fromisoformat(times.pop()),
            mode=modes.pop(), provenance={"kind": "original_recorded_capture",
                "original_normalized_json_sha256": manifest["files"][relative]["sha256"],
                "source_zip_sha256": manifest["source_zip_sha256"]})
        require(len(snap.records) == len(legacy), "Raw XML/legacy row counts differ")
        # Older JSON was saved before time/market normalization improvements.
        # Keep it unchanged; report those differences rather than treating it as truth.
        differences = Counter()
        for parsed, old in zip(snap.records, legacy):
            for k, v in parsed.items():
                if old.get(k) != v:
                    differences[k] += 1
        report.append({"capture_id": capture_id, "retrieved_at": snap.retrieved_at.isoformat(),
            "mode": snap.retrieval_mode, "rows": len(snap.records), "raw_sha256": snap.raw_sha256,
            "differences_from_legacy_json": dict(differences)})
        captures.append(snap)
    return tuple(captures), report


def replay_original_current(folder, captures):
    current = sorted((s for s in captures if s.retrieval_mode == "CURRENT"), key=lambda s: s.retrieved_at)
    require(len(current) == 4, "Expected the four uploaded CURRENT captures")
    at = current[0].retrieved_at
    session = at.astimezone(ET).date()
    universe = frozenset(r["symbol"] for s in current for r in s.records) | {"SPY"}
    ledger = SamplingRequestStore(folder / "original_requests.sqlite3", session_date=session,
        baseline=SamplingMembership(universe, frozenset(), frozenset()), clock=lambda: at)
    ledger.initialize()
    producer = NasdaqSamplingProducer(folder / "original_producer.sqlite3", request_store=ledger,
        settings=HaltProducerSettings("nasdaq-recorded-replay", ("LUDP", "M"), "regular_close", False),
        clock=lambda: at)
    producer.initialize()
    for snap in current:
        at = snap.retrieved_at
        producer.record_snapshot(snap)
        producer.deliver_pending()
    result = plain(producer.snapshot())
    require(not ledger.events(), "After-hours original sequence unexpectedly submitted requests")
    result["request_receipts"] = 0
    result["interpretation"] = "Offline replay of original after-hours captures; no live detection or promotion claim"
    return result


class Clock:
    def __init__(self):
        # Next calendar date is a hypothetical fixture session, even on weekends.
        self.session = datetime.now(ET).date() + timedelta(days=1)
        self.start = datetime.combine(self.session, time(9, 30), ET)
        self.value = self.start

    def at(self, seconds): self.value = self.start + timedelta(seconds=seconds)
    def __call__(self): return self.value


def simulation_fixture(folder, captures):
    source = next(s for s in captures if s.capture_id == "2026-08-14-17-01-37-CURRENT")
    original = sorted((r for r in source.records if r["symbol"] == "AEHL" and r["reason_code"] == "LUDP"),
                      key=lambda r: r["halt_time"])
    require(len(original) >= 2, "Expected two distinct recorded AEHL halt examples")
    clock = Clock()
    baseline = SamplingMembership(frozenset({"AEHL", "AAPL", "SPY"}), frozenset({"SPY"}), frozenset())
    ledger = SamplingRequestStore(folder / "simulation_requests.sqlite3", session_date=clock.session,
        baseline=baseline, clock=clock, policy=PROOF_POLICY)
    ledger.initialize()
    producer = NasdaqSamplingProducer(folder / "simulation_producer.sqlite3", request_store=ledger,
        settings=HaltProducerSettings("nasdaq-proof", ("LUDP", "M"), "regular_close", True), clock=clock)
    producer.initialize()
    journal = QuoteObservationStore(folder / "simulation_membership.sqlite3", session_date=clock.session, schema_version=2)
    journal.initialize()
    journal.record_membership_revision(SamplingHierarchyRevision(session_date=clock.session, revision=0,
        effective_at=clock.start, uni_symbols=tuple(baseline.uni), focus_symbols=tuple(baseline.focus), hot_symbols=(),
        source=SOURCE, reason="Hypothetical next-calendar-day session; original captures remain unchanged",
        metadata={"experimental": True, "synthetic_policy_clock": True,
            "request_baseline_sha256": ledger.states()[0].event_sha256}))

    def derived(cid, rows):
        return HaltSnapshot(cid, source.retrieved_at, "CURRENT", source.raw_sha256, tuple(rows),
            {"kind": "derived_arrival_simulation", "source_capture_id": source.capture_id,
             "original_capture_retrieved_at": source.retrieved_at.isoformat(),
             "derivation": "Original baseline; selected AEHL examples get hypothetical dates/times below",
             "not_an_observed_live_sequence": True})

    def remap(row, seconds):
        at = clock.start + timedelta(seconds=seconds)
        return {**plain(row), "halt_date": at.strftime("%m/%d/%Y"), "halt_time": at.strftime("%H:%M:%S.%f"),
                "original_record": plain(row), "original_event_id": halt_event_id(row),
                "time_mapping": "Explicit hypothetical fixture halt time; not Nasdaq event time"}

    return ledger, producer, journal, clock, derived, remap, source, original


def exercise_simulation(fixture):
    ledger, producer, journal, clock, derived, remap, source, original = fixture
    trace = []
    def note(label):
        trace.append({"label": label, "logical_at": clock().isoformat(), "state": ledger.states()[-1].payload()})
    producer.record_snapshot(derived("simulation-baseline", source.records))
    require(not producer.snapshot()["pending"], "Startup history was treated as new")
    first, second = remap(original[0], 1), remap(original[1], 8)
    clock.at(2); producer.record_snapshot(derived("simulation-first", [first]))
    def fail(_): raise RuntimeError("Injected interruption after request commit before acknowledgement")
    try:
        producer.deliver_pending(after_submit=fail)
    except RuntimeError as exc:
        require(str(exc).startswith("Injected"), "Unexpected delivery failure")
    else: raise RuntimeError("Interruption did not occur")
    first_receipt = ledger.events()[0]
    before = producer.snapshot()
    producer = NasdaqSamplingProducer(producer.path, request_store=ledger, settings=producer.settings, clock=clock)
    producer.initialize()
    require(producer.snapshot() == before, "Producer restart changed input state")
    require(not producer.deliver_pending()[0].inserted and ledger.events()[0] == first_receipt,
            "Retry duplicated or moved the first request receipt")
    note("first halt promoted; interrupted delivery recovered")
    clock.at(3)
    ledger.submit_request(ProducerIntent("manual", "manual", IntentType.ENSURE_PRESENT, frozenset({"AEHL"}),
        clock(), metadata={"sampling_channel": "hot", "session_date": ledger.session_date.isoformat()}), actor_id="manual")
    clock.at(4); ledger.cancel_request("manual-withdraw", owner_id="manual", request_id="manual", actor_id="manual")
    require(ledger.states()[-1].applied.hot == {"AEHL"}, "Manual withdrawal erased Nasdaq demand")
    note("manual withdrawal leaves Nasdaq demand")
    clock.at(5); producer.record_snapshot(derived("simulation-repeat", [first])); require(not producer.deliver_pending(), "Repeated event duplicated")
    clock.at(6); producer.record_snapshot(derived("simulation-update", [{**first, "reason_code": "T3", "resumption_trade_time": "09:35:00"}]))
    require(not producer.deliver_pending(), "Mutable update became another halt request")
    clock.at(7); ledger.restrict_symbol("cap", symbol="AEHL", max_group="focus", actor_id="proof-super-user")
    clock.at(9); producer.record_snapshot(derived("simulation-second", [second])); producer.deliver_pending()
    require(not ledger.states()[-1].applied.hot, "A new source request bypassed the restriction")
    note("later distinct halt retained under restriction")
    clock.at(10); ledger.clear_restriction("clear", symbol="AEHL", restriction_id="cap", actor_id="proof-super-user")
    clock.at(11); ledger.cancel_request("first-withdraw", owner_id="nasdaq-proof", request_id=first_receipt.command_id, actor_id="nasdaq-proof")
    require(ledger.states()[-1].applied.hot == {"AEHL"}, "First-event withdrawal erased the second event")
    note("clear restores current demand; distinct second request survives first withdrawal")
    return producer, trace


def publish_states(ledger, journal):
    revisions = journal.membership_revisions_in_effective_order()
    states, events = ledger.states(), ledger.events()
    require(revisions and revisions[0].source == SOURCE, "Wrong simulation journal identity")
    opening = revisions[0]
    require(opening.session_date == ledger.session_date and opening.metadata["request_baseline_sha256"] == states[0].event_sha256,
            "Journal and request identity differ")
    require({c: list(opening.symbols_for(c)) for c in ("uni", "focus", "hot")} == membership_payload(ledger.baseline),
            "Journal and request baseline membership differ")
    require(len(revisions) <= len(states), "Journal is ahead of the request ledger")
    proposals = []
    previous_effective = opening.effective_at
    for state, event in zip(states[1:], events):
        effective = max(previous_effective + timedelta(microseconds=1), state.as_of + timedelta(microseconds=1))
        require(opening.published_at <= state.as_of and effective > opening.effective_at,
                "Simulation knowledge cannot precede baseline publication")
        for active in (*state.active_requests, *state.active_restrictions):
            expiry = active.get("expires_at_utc")
            require(expiry is None or datetime.fromisoformat(expiry) > effective,
                    "Active demand/control expires before scheduled publication")
        proposals.append(SamplingHierarchyRevision(session_date=ledger.session_date, revision=state.sequence,
            effective_at=effective, uni_symbols=tuple(state.applied.uni), focus_symbols=tuple(state.applied.focus),
            hot_symbols=tuple(state.applied.hot), source=SOURCE, reason=f"Simulated request receipt {state.sequence}",
            metadata={"experimental": True, "synthetic_policy_clock": True, "derived_arrival_simulation": True,
                      "request_state": state.payload(), "input_event": event.hash_payload(),
                      "request_baseline_sha256": states[0].event_sha256}))
        previous_effective = effective
    for old, candidate in zip(revisions[1:], proposals):
        require(old.content_sha256 == candidate.content_sha256, "Published prefix differs from request replay")
    return tuple(journal.record_membership_revision(p) for p in proposals)


def run_proof(folder):
    captures, inventory = load_captures()
    originals = replay_original_current(folder, captures)
    fixture = simulation_fixture(folder, captures)
    ledger, _, journal, clock, *_ = fixture
    producer, trace = exercise_simulation(fixture)
    require(all(r == RecordResult.INSERTED for r in publish_states(ledger, journal)), "Initial publication failed")
    require(all(r == RecordResult.ALREADY_PRESENT for r in publish_states(ledger, journal)), "Publication retry was not idempotent")
    a, b = journal_replay(journal.database_path), journal_replay(journal.database_path)
    require(a == b, "Journal replays differ")
    require([x["membership"] for x in a] == [membership_payload(s.applied) for s in ledger.states()], "Replay membership differs")
    audit = audit_quote_journal(journal.database_path)
    require(audit.passed and audit.table_counts["quote_acquisition"] == 0, "Audit failed or unexpected acquisition")
    report = {"result": "PASS", "source_inventory": inventory,
        "original_current_replay": originals, "simulation_trace": trace,
        "simulation_producer": plain(producer.snapshot()), "simulation_request_states": [s.payload() for s in ledger.states()],
        "simulation_journal_checkpoints": a, "synthetic_policy_clock": True,
        "hypothetical_session_date": clock.session.isoformat(), "policy_settings": PROOF_POLICY.payload(),
        "producer_settings": producer.settings.payload(), "production_defaults": False,
        "audit": "PASS", "request_replay_sha256": digest([s.payload() for s in ledger.states()]),
        "journal_replay_sha256": digest(a), "producer_replay_sha256": digest(producer.snapshot()),
        "table_counts": dict(audit.table_counts)}
    (folder / "proof_report.json").write_text(json.dumps(report, indent=2) + "\n")
    summary = "\n".join(["Recorded Nasdaq adapter proof: PASS",
        f"Original captures: {len(captures)}; parsed rows: {sum(len(s.records) for s in captures)}; exact source hashes verified",
        "Original CURRENT replay: four after-hours snapshots; zero promotion requests",
        "Promotion sequence: derived simulation using recorded AEHL examples; original timestamps retained",
        "Startup baseline, repeats, updates and later distinct halt: PASS",
        "Request-commit/ack interruption and restart: PASS; no duplicate request",
        "Manual withdrawal and privileged restriction interaction: PASS",
        "Proof settings: LUDP/M; fixed Uni; requests until 16:00 ET; replay clock; no production defaults",
        f"Simulation: {len(producer.snapshot()['receipts'])} producer receipts; {len(ledger.events())} request receipts; {len(a)} hierarchy revisions",
        "Journal audit: PASS; two replays identical; publication retry idempotent; market acquisitions: 0",
        "No live halt latency, running publication service or Hot acquisition claim",
        "Request replay SHA-256: " + report["request_replay_sha256"],
        "Journal replay SHA-256: " + report["journal_replay_sha256"], ""])
    (folder / "proof_report.txt").write_text(summary)
    return report
