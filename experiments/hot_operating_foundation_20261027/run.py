"""Pinned packet entry: offline qualification, operating review, deployment."""
from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import time
import unittest
from uuid import uuid4

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("operating_release", ROOT/"release.py")
release = importlib.util.module_from_spec(spec); spec.loader.exec_module(release)


def sources(*, testing=False):
    paths = [ROOT/"coordinator/src", ROOT/"market_data/src"]
    if testing:
        paths += [ROOT/"market_data/tests", ROOT/"coordinator/tests", ROOT/"reference_helpers/src", ROOT/"offline_bootstrap"]
    sys.path[:0] = [str(p) for p in paths]
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    sys.dont_write_bytecode = True
    if testing:
        os.environ["PYTHONPATH"] = os.pathsep.join(str(p) for p in paths)


def qualify(manifest):
    sources(testing=True)
    # Also applied automatically to the only child Python operations: native
    # saved-journal replay and synthetic file/process tests.
    network = importlib.util.spec_from_file_location("operating_offline_network", ROOT/"offline_bootstrap/sitecustomize.py")
    block = importlib.util.module_from_spec(network); network.loader.exec_module(block)
    from mb_market_data.acquisition_health import atomic_json
    directory = ROOT/"runs/qualification"/(datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ_")+uuid4().hex[:8])
    directory.mkdir(parents=True, exist_ok=False)
    previous = ROOT/"ACCEPTED.json"
    if previous.is_file():
        (directory/"previous-acceptance.json").write_bytes(previous.read_bytes())
    atomic_json(previous, {"result": "QUALIFYING", "windows_accepted": False})
    print("OFFLINE operating foundation: synthetic journals/credentials only; no API, password or production process changes.", flush=True)
    names = ['test_polling_cadence','test_watchlist_polling','test_acquisition_health',
        'test_quote_observation_store','test_quote_journal_audit','test_quote_journal_replay',
        'test_observation_overlay','test_observation_overlay_view','test_quote_dashboard_replay',
        'test_quote_dashboard_probe','test_universe_quote_watch_credentials','test_polling_health_status',
        'test_monitor_status_recovery','test_operating_plan','test_operating_release']
    started = time.monotonic()
    suite = unittest.defaultTestLoader.loadTestsFromNames(names)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    release.load_manifest()  # Source inventory must still match after tests.
    allowed = ({'test_monitor_status_recovery.StatusRecoveryTests.test_real_windows_reader_lock_releases_and_same_publication_succeeds'}
               if os.name != "nt" else set())
    unexpected = [t.id() for t, reason in result.skipped if t.id() not in allowed]
    passed = result.wasSuccessful() and not unexpected
    report = {
        "contract": "hot-operating-foundation-offline-qualification-v1",
        "result": "PASS" if passed else "FAILED", "tests": result.testsRun,
        "passed": result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped),
        "failures": len(result.failures), "errors": len(result.errors), "skipped": len(result.skipped),
        "failed_tests": [t.id() for t,e in result.failures+result.errors],
        "skipped_tests": [{"test": t.id(), "reason": reason} for t,reason in result.skipped],
        "seconds": time.monotonic()-started, "network": "denied", "actual_vault_access": False,
        "production_changes": False, "hot_enabled": False,
        "market_data_source_commit": manifest["source_commit"],
        "coordinator_source_commit": manifest["coordinator_source_commit"],
        "release_sha256": release.sha(ROOT/"RELEASE.json"),
        "windows_accepted": bool(passed and os.name == "nt" and not result.skipped),
        "python": list(sys.version_info[:3]), "platform": sys.platform,
        "daily_hot_driver_included": False,
        "source_runtime_and_accepted_live_profiles_repeated": False,
        "remaining": ["Windows result and actual CMD prompt return", "Review candidate operating values",
            "Separate approval before production source/cadence installation",
            "Fresh-session Uni/Focus cadence validation with Hot disabled and native full-session audit/replay",
            "Daily Hot driver and operating-release integration; manual membership and agreed read-only Overlay"]}
    atomic_json(directory/"verification.json", report)
    atomic_json(previous, report)
    print(json.dumps(report, indent=2), flush=True)
    print("Saved report:", directory/"verification.json", flush=True)
    return 0 if passed else 1


def main():
    try:
        manifest = release.load_manifest()
        if len(sys.argv) < 2: return 64
        role = sys.argv[1]
        if role == "verify" and len(sys.argv) == 2:
            return qualify(manifest)
        sources()
        if role == "plan":
            from mb_watchlist_coordinator.operating_plan import main as plan
            return plan(sys.argv[2:])
        if role in ("review", "install", "rollback"):
            return release.main(sys.argv[1:])
        return 64
    except KeyboardInterrupt:
        return 130
    except Exception as error:
        print("Operating foundation STOPPED:", type(error).__name__, str(error), flush=True)
        return 70


if __name__ == "__main__": raise SystemExit(main())
