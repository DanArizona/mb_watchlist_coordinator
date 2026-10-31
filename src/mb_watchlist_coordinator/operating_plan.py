"""Reviewable daily settings and independent process commands.

This first operating increment prepares a Hot-disabled cadence-validation
session. Proposed Hot policy is explicit but cannot activate a daily Hot driver.
No credential or network API is imported or invoked by planning.
"""
from __future__ import annotations

import argparse
from datetime import datetime, time
import json
from pathlib import Path
import subprocess
from zoneinfo import ZoneInfo

from .controller_bootstrap import _proposal, strict_json
from .sampling_policy import SamplingPolicy
from .sampling_requests import digest

ET = ZoneInfo("America/New_York")
POLICY = {
    "contract": "hot-operating-policy-proposal-v1",
    "status": "PROPOSED_NOT_ADOPTED",
    "cadence_profile": "interleaved-v1",
    "hot_enabled": False,
    "reason_codes": ["LUDP", "M"],
    "request_lifetime": "regular_close",
    "operator_actor_id": "operator:masterbot",
    "limits": {
        "maximum_active_hot_symbols": 1,
        "maximum_distinct_added_symbols_per_session": 1,
        "maximum_hot_quote_calls": 9360,
        "maximum_identity_quote_calls": 3,
        "maximum_directory_retrievals": 2,
        "maximum_feed_attempts": 390,
        "feed_seconds_after_completion": 60,
        "maximum_worker_starts": 3,
    },
    "stabilization": {"demotion_grace_seconds": 60, "minimum_residence_seconds": 120,
                      "restriction_timing": "immediate_cap"},
    "deadlines": {"worker_progress_seconds": 3, "credential_seconds": 8,
                  "worker_replacement_hold_seconds": 15, "cleanup_seconds": 10,
                  "reporting_seconds": 60},
    "source_warnings": ["intermediate_feed_mutations_not_reconstructible",
                        "older_unknown_carryovers_not_proven_complete",
                        "provider_collector_driver_qualification_pending"],
}


MULTI_PROFILE = 'multi-40-v1'
SINGLE_PROFILE = 'single-v1'


def proposed_policy(profile=SINGLE_PROFILE) -> dict:
    value = json.loads(json.dumps(POLICY))
    if profile == MULTI_PROFILE:
        value['contract'] = 'hot-multisymbol-operating-policy-proposal-v1'
        value['limits'].update(maximum_active_hot_symbols=40,
            maximum_distinct_added_symbols_per_session=40,
            maximum_identity_quote_calls=120,
            identity_seconds_between_calls=2,
            maximum_identity_calls_per_symbol=3)
        value['publication']={'minimum_interval_seconds':10,'pending_membership_visible':True}
        value['collection_history'] = {'active_period_seconds':300,
            'full_schedule_registered':True,
            'closed_payload_validation':'independent_full_journal_audit_and_replay'}
    elif profile != SINGLE_PROFILE:
        raise ValueError('Unknown sealed daily policy profile')
    return value


def validate_policy(value: dict) -> dict:
    # Candidate policy values are deliberately sealed in this increment.
    # Editing a JSON file cannot silently widen scope or enable a missing driver.
    profiles = (SINGLE_PROFILE, MULTI_PROFILE)
    profile = next((p for p in profiles if digest(value) == digest(proposed_policy(p))), None)
    if (not isinstance(value, dict) or profile is None
            or type(value.get("hot_enabled")) is not bool):
        raise ValueError("Policy differs from the explicit Hot-disabled review candidate")
    SamplingPolicy(value["operator_actor_id"], **value["stabilization"])
    return proposed_policy(profile)


def build_plan(opening_path: Path, focus_path: Path, *, market_data_root: Path,
               ecfg_path: Path, policy: dict | None = None, executable: str = "python") -> dict:
    from mb_market_data.polling_cadence import CADENCE_PROFILES, RESERVED_HOT_SECONDS
    policy = validate_policy(proposed_policy() if policy is None else policy)
    opening, h0 = _proposal(opening_path)
    focus, h1 = _proposal(focus_path)
    day = opening.session_date
    start = datetime.combine(day, time(9, 30), ET)
    stop = datetime.combine(day, time(16), ET)
    if (opening.revision != 0 or focus.revision != 1 or focus.session_date != day
            or opening.effective_at != start or focus.effective_at != start
            or opening.uni_symbols != focus.uni_symbols or not opening.uni_symbols
            or opening.focus_symbols or opening.hot_symbols or focus.hot_symbols
            or not 1 <= len(focus.focus_symbols) <= 40):
        raise ValueError("Opening/Focus proposals must describe one dated 09:30 hierarchy with Hot empty")
    root = Path(market_data_root)
    if not root.is_absolute() or not Path(ecfg_path).is_absolute():
        raise ValueError("Explicit absolute market-data and configuration paths are required")
    profile = policy["cadence_profile"]
    seconds = {channel: list(slots) for channel, slots in CADENCE_PROFILES[profile].items()}
    journal = root/"output"/f"quote_observation_journal_v2_api_opening_{day}"/f"{day}.sqlite3"
    source = {"opening": {"path": str(opening_path), "file_sha256": h0,
                          "content_sha256": opening.content_sha256},
              "focus": {"path": str(focus_path), "file_sha256": h1,
                        "content_sha256": focus.content_sha256}}
    common = ["--start-at", start.isoformat(), "--stop-at", stop.isoformat(),
              "--journal-root", str(journal.parent), "--journal-schema-version", "2",
              "--cadence-profile", profile, "--batch-size", "400", "--ecfg", str(ecfg_path)]
    commands = {channel: [executable, str(root/"probes/probe_universe_quote_watch.py"),
                          "--watchlist-kind", channel, *common] for channel in seconds}
    health = [executable, str(root/"probes/polling_health.py")]
    health_args = ["--market-data-root", str(root), "--session-date", str(day),
                   "--cadence-profile", profile]
    commands["health"] = [*health, "monitor", *health_args, "--supervise"]
    commands["status"] = [*health, "monitor", *health_args, "--once", "--no-popup"]
    commands["stop_health"] = [*health, "stop-monitor", *health_args]
    for channel in seconds:
        commands["restart_"+channel] = [*health, "restart", *health_args, "--channel", channel]
    # Read-only readiness is descriptive. Publication/r1 hashes are not inferred
    # from a proposal, nor is the current day's legacy session replaced.
    readiness = "FRESH_SESSION_REQUIRED"
    if journal.is_file():
        from mb_market_data.polling_cadence import check_before_credentials
        try:
            check_before_credentials(journal, profile)
            readiness = "CADENCE_COMPATIBLE_PUBLICATION_REVIEW_REQUIRED"
        except ValueError:
            readiness = "EXISTING_SESSION_CADENCE_CONFLICT"
    calls_uni = ((len(opening.uni_symbols)+1+399)//400)*780
    content = {
        "contract": "daily-hot-operating-review-plan-v1", "session_date": str(day),
        "status": "REVIEW_CANDIDATE_HOT_DISABLED", "policy": policy,
        "source_proposals": source, "journal": str(journal),
        "opening_counts": {"uni": len(opening.uni_symbols), "focus": len(focus.focus_symbols), "hot": 0},
        "window": {"start_at_et": start.isoformat(), "stop_at_et": stop.isoformat(), "stop_excluded": True},
        "cadence_seconds": seconds, "reserved_future_hot_seconds": list(RESERVED_HOT_SECONDS),
        "expected_full_session_slots": {"uni": 780, "focus": 1560, "future_hot": 9360},
        "proposed_maximum_schwab_calls": {"uni_with_one_possible_addition": calls_uni,
             "focus": 1560, "future_hot": 9360, "future_identity": 3,
             "total_if_future_hot_is_qualified_and_adopted": calls_uni+1560+9360+3},
        "cadence_readiness": readiness,
        "commands": commands,
        "commands_windows": {name: subprocess.list2cmdline(argv) for name, argv in commands.items()},
        "independent_windows": ["prod-poll-uni", "prod-poll-focus", "prod-health"],
        "future_hot_driver": {"implemented_in_this_increment": False, "launch_command": None,
                              "activation_allowed": False},
        "process_failure_boundary": "A controller/Hot failure must leave healthy Uni, Focus and independent Health running.",
        "approval": "Windows qualification and explicit production-change approval are required before source installation or cadence rollout.",
        "acceptance_after_rollout": "Fresh full Uni/Focus session with Hot disabled; native audit and complete replay.",
        "rollback": "At the next fresh session boundary, use the original commands without --cadence-profile (legacy default); never switch an active session's cadence.",
        "proposal_scope": "Candidate daily Hot values are not adopted settings or a qualified daily Hot collector."
    }
    return dict(content, plan_sha256=digest(content))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("opening", type=Path)
    parser.add_argument("focus", type=Path)
    parser.add_argument("--market-data-root", type=Path, required=True)
    parser.add_argument("--ecfg", type=Path, required=True, help="Path only; this command never opens the encrypted configuration")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        plan = build_plan(args.opening, args.focus, market_data_root=args.market_data_root, ecfg_path=args.ecfg)
        if args.output_dir:
            directory = args.output_dir.resolve()
            if (any(part.lower().startswith("quote_observation_journal") for part in directory.parts)
                    or directory.suffix in (".sqlite3", ".db")):
                raise ValueError("Plan output must be separate from acquisition journals")
            directory.mkdir(parents=True, exist_ok=False)
            (directory/"operating-plan.json").write_text(json.dumps(plan, indent=2)+"\n", encoding="utf-8")
            print(f"Saved operating review plan: {directory/'operating-plan.json'}")
        print(json.dumps(plan, indent=2))
        return 0
    except (OSError, ValueError) as error:
        print(f"Operating plan ERROR: {error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
