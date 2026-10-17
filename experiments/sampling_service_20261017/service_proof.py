"""Bounded real-process loop plus process-exit recovery at both commit boundaries."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from mb_market_data.quote_journal_audit import audit_quote_journal
from mb_market_data.quote_observation_store import QuoteObservationStore
from mb_watchlist_coordinator.sampling_journal import SamplingJournal
from mb_watchlist_coordinator.sampling_policy import SamplingPolicy
from mb_watchlist_coordinator.sampling_projection import SamplingMembership
from mb_watchlist_coordinator.sampling_request_store import SamplingRequestStore
from mb_watchlist_coordinator.sampling_requests import digest, plain, timestamp
from mb_watchlist_coordinator.sampling_service import PublicationSettings, SamplingPublicationService
from request_proof import journal_replay, require
from test_sampling_service import fixture, request

EXPERIMENT = Path(__file__).resolve().parent


def save_config(folder, service, *, logical_now=None):
    value = {"request_identity": plain(service.requests.identity), "settings": service.settings.payload(),
             "logical_now": logical_now.isoformat() if logical_now is not None else None}
    (folder / "worker_config.json").write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def load_service(folder):
    value = json.loads((folder / "worker_config.json").read_text(encoding="utf-8"))
    identity = value["request_identity"]
    baseline = SamplingMembership(**{k: frozenset(v) for k, v in identity["baseline"].items()})
    clock = (lambda: timestamp(value["logical_now"])) if value["logical_now"] else (lambda: datetime.now(timezone.utc))
    ledger = SamplingRequestStore(folder / "requests.sqlite3", session_date=date.fromisoformat(identity["session_date"]),
        baseline=baseline, policy=SamplingPolicy(**identity["policy"]), clock=clock)
    settings = PublicationSettings(**dict(value["settings"], publish_until=timestamp(value["settings"]["publish_until"])))
    store = QuoteObservationStore(folder / "membership.sqlite3", session_date=ledger.session_date, schema_version=2)
    service = SamplingPublicationService(folder / "publication.sqlite3", request_store=ledger,
        journal=SamplingJournal(store), settings=settings, clock=clock)
    service.initialize()
    return ledger, store, service


def child(folder, stage):
    return subprocess.Popen([sys.executable, "-I", "-B", str(EXPERIMENT / "service_worker.py"), str(folder), stage],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def wait_for(predicate, description, *, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        threading.Event().wait(0.025)
    raise RuntimeError("Timed out waiting for " + description)


def read_status(folder):
    path = folder / "worker_status.jsonl"
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")[:-1]  # ignore an in-progress final line
    return json.loads(lines[-1]) if lines else {}


def run_proof(folder):
    real = folder / "real_process"; real.mkdir()
    # Accelerated demonstration settings, not production defaults. Logical fault
    # drills separately include the already-reviewed 60/120 second policy.
    policy = SamplingPolicy("proof-super-user", 0.4, 0.8, "immediate_cap")
    ledger, store, service, _ = fixture(real, policy=policy, real_clock=True,
        settings_values={"publication_lead_seconds": 0.35,
                         "publish_until": datetime.now(timezone.utc) + timedelta(seconds=35)})
    save_config(real, service)
    worker = child(real, "run")
    trace = []
    start = time.monotonic()

    def membership(hot, *, after=-1):
        value = store.membership_revisions_in_effective_order()[-1]
        if value.revision > after and value.hot_symbols == hot and value.effective_at <= datetime.now(timezone.utc):
            return value
        return None

    def record(label, value):
        trace.append({"label": label, "revision": value.revision,
                      "observed_at_utc": datetime.now(timezone.utc).isoformat(),
                      "effective_at_utc": value.effective_at.isoformat(),
                      "journal_published_at_utc": value.published_at.isoformat(),
                      "content_sha256": value.content_sha256,
                      "hot": list(value.hot_symbols), "focus": list(value.focus_symbols)})

    try:
        wait_for(lambda: read_status(real), "worker startup")
        request(ledger, "m1", "manual")
        promoted = wait_for(lambda: membership(("MSFT",)), "manual Hot promotion")
        record("manual promotion", promoted)
        request(ledger, "h1", "synthetic-halt")
        ledger.cancel_request("m-cancel", owner_id="manual", request_id="m1", actor_id="manual")
        target = len(ledger.events())
        wait_for(lambda: read_status(real).get("processed_sequence", -1) >= target,
                 "manual withdrawal processed while halt demand remains")
        require(membership(("MSFT",)) is not None, "Manual withdrawal removed independent halt demand")
        record("manual withdrawal retains synthetic halt demand", membership(("MSFT",)))
        ledger.restrict_symbol("cap", symbol="MSFT", max_group="uni", actor_id="proof-super-user",
                              expires_at=datetime.now(timezone.utc) + timedelta(seconds=2.0))
        capped = wait_for(lambda: membership((), after=promoted.revision), "privileged cap")
        record("privileged cap", capped)
        restored = wait_for(lambda: membership(("MSFT",), after=capped.revision), "timer-driven cap expiry")
        record("cap expiry restores current demand", restored)
        ledger.cancel_request("h-cancel", owner_id="synthetic-halt", request_id="h1", actor_id="synthetic-halt")
        demoted = wait_for(lambda: membership((), after=restored.revision), "timer-driven ordinary demotion")
        record("last withdrawal followed by delayed demotion", demoted)
    finally:
        (real / "STOP").write_text("stop\n", encoding="utf-8")
        try:
            output, _ = worker.communicate(timeout=8)
        except subprocess.TimeoutExpired:
            worker.kill(); output, _ = worker.communicate()
            raise RuntimeError("Bounded service worker did not stop; terminated isolated child")
        (real / "worker_output.txt").write_text(output, encoding="utf-8")
    require(worker.returncode == 0, f"Service worker failed: {output}")
    status = read_status(real)
    require(status["status"] == "stopped", "Worker did not report its stopped state")
    require(status["pid"] != __import__("os").getpid(), "Proof worker did not run as an independent process")
    require(status["cycles"] > 1, "Expected repeated real running cycles")
    s = plain(service.snapshot())
    require(s["pending"] is None, "Unacknowledged real-process plan remains")
    require(any(e.kind == "tick" for e in ledger.events()), "No timer tick was durably recorded")
    a, b = journal_replay(store.database_path), journal_replay(store.database_path)
    require(a == b, "Real-process journal replays differ")
    require([r["membership"]["hot"] for r in a] == [[], ["MSFT"], [], ["MSFT"], []], "Unexpected real-process membership trace")
    audit = audit_quote_journal(store.database_path)
    require(audit.passed and audit.table_counts["quote_acquisition"] == 0, "Isolated service journal audit/acquisition guard failed")
    restarted = load_service(real)[2]
    require(plain(restarted.snapshot()) == s, "Reopening changed publication outcomes")
    recovered = []
    for stage in ("after_plan", "after_commit"):
        fault = folder / stage; fault.mkdir()
        l, j, svc, clock = fixture(fault)
        request(l)
        save_config(fault, svc, logical_now=clock[0])
        process = child(fault, stage)
        try:
            output, _ = process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill(); process.communicate()
            raise RuntimeError(f"Isolated fault worker timed out at {stage}")
        require(process.returncode == 73, f"Fault worker did not exit at {stage}: {output}")
        before = j.membership_revisions_in_effective_order()
        clock[0] += timedelta(seconds=2)
        svc = SamplingPublicationService(svc.path, request_store=l, journal=SamplingJournal(j),
                                         settings=svc.settings, clock=lambda: clock[0])
        svc.initialize(); svc.cycle()
        after = j.membership_revisions_in_effective_order()
        require(len(after) == 2 and after[-1].hot_symbols == ("MSFT",), "Recovery duplicated or lost promotion")
        require(plain(svc.snapshot())["pending"] is None, "Recovery left a pending publication")
        if stage == "after_commit":
            require(before[-1] == after[-1], "Recovery changed committed content or publication receipt")
        else:
            require(after[-1].effective_at > clock[0], "Recovery backdated an uncommitted plan")
        r1, r2 = journal_replay(j.database_path), journal_replay(j.database_path)
        require(r1 == r2 and audit_quote_journal(j.database_path).passed, "Fault recovery audit/replay failed")
        recovered.append({"stage": stage, "exit_code": process.returncode,
                          "clock": "injected future logical fault drill; store publication clock is real",
                          "outcomes": plain(svc.snapshot())["outcomes"], "journal_replay_sha256": digest(r1)})
    report = {"result": "PASS", "real_process": True, "elapsed_seconds": round(time.monotonic() - start, 3),
              "worker": status, "trace": trace, "request_events": [dict(e.hash_payload(), event_sha256=e.event_sha256) for e in ledger.events()],
              "publication_outcomes": s["outcomes"], "policy_settings": policy.payload(),
              "service_settings": service.settings.payload(), "settings_status": "accelerated_proof_only_no_production_defaults",
              "recovery": recovered, "journal_audit": "PASS", "table_counts": dict(audit.table_counts),
              "journal_replay_sha256": digest(a), "outcome_replay_sha256": s["head_sha256"],
              "limits": "No network, live halt latency, authentication, production journal, Hot acquisition or capacity claim"}
    (folder / "proof_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    summary = "\n".join([
        "Running Coordinator publication proof: PASS",
        "Independent process: actual wall clock, local requests, repeated cycles and clean stop",
        "Manual + synthetic halt demand; privileged cap; automatic expiry and delayed demotion: PASS",
        "Process exit before journal commit: rechecked and rescheduled; no backdating",
        "Process exit after journal commit: original revision and publication receipt acknowledged; no duplicate",
        "Durable plans/outcomes, complete revisions, audit and two identical replays: PASS",
        "Review settings only; unit timer drills include 60s grace / 120s residence",
        "Real loop uses accelerated 0.4s grace / 0.8s residence, 0.35s publication lead, 0.05s local polling",
        f"Real process cycles: {status['cycles']}; hierarchy revisions: {len(a)}; market acquisitions: 0",
        "No live Nasdaq, brokerage request, password, production change or Hot polling",
        f"Journal replay SHA-256: {report['journal_replay_sha256']}",
        f"Publication outcomes SHA-256: {report['outcome_replay_sha256']}", ""])
    (folder / "proof_report.txt").write_text(summary, encoding="utf-8")
    return report
