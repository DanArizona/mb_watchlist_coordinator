"""One non-interactive restriction/demotion check with a synthetic policy clock."""

from __future__ import annotations

import hashlib
import io
import json
import sys
import tempfile
import traceback
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path


def verify_sources(root: Path, experiment: Path):
    manifest = json.loads((experiment / "source_manifest.json").read_text(encoding="utf-8"))
    for relative, expected in manifest["files_sha256_lf"].items():
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError(f"Missing or invalid proof source: {relative}")
        if hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest() != expected:
            raise ValueError(f"Source differs from the reviewed payload: {relative}")
    return manifest


def main():
    sys.dont_write_bytecode = True
    experiment = Path(__file__).resolve().parent
    root = experiment.parent.parent
    run = None
    try:
        if len(sys.argv) != 1:
            raise ValueError("This proof accepts no arguments or external database paths")
        manifest = verify_sources(root, experiment)
        sys.path[:0] = [str(root / "src"),
                        str(root / "experiments/sampling_promotion_20261016/market_data/src"),
                        str(root / "experiments/sampling_requests_20261016"), str(experiment)]
        runs = experiment / "runs"
        if runs.resolve().parent != experiment:
            raise ValueError("runs must remain under this experiment")
        runs.mkdir(exist_ok=True)
        run = runs / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8])
        run.mkdir()
        scratch = run / "temporary_tests"
        scratch.mkdir()
        tempfile.tempdir = str(scratch)
        print("COORDINATOR RESTRICTIONS AND DEMOTION - synthetic policy proof", flush=True)
        suite = unittest.TestSuite()
        suite.addTests(unittest.TestLoader().discover(str(root / "tests"), pattern="test_sampling_policy.py"))
        suite.addTests(unittest.TestLoader().discover(str(experiment), pattern="test_policy_publication.py"))
        output = io.StringIO()
        result = unittest.TextTestRunner(stream=output, verbosity=2).run(suite)
        (run / "test_results.txt").write_text(output.getvalue(), encoding="utf-8")
        print(output.getvalue(), end="", flush=True)
        if result.testsRun != 43 or not result.wasSuccessful():
            raise RuntimeError("Expected all 43 focused tests to pass")
        from policy_proof import run_proof
        report = run_proof(run)
        loaded = {}
        for name, module in tuple(sys.modules.items()):
            if name.startswith(("mb_watchlist_coordinator", "mb_market_data")):
                path = Path(module.__file__).resolve()
                if not path.is_relative_to(root):
                    raise ValueError(f"Imported external source: {name}")
                loaded[name] = str(path.relative_to(root))
        receipt = {"result": "PASS", "tests_run": result.testsRun, "synthetic_policy_clock": True,
                   "policy_settings": report["policy_settings"],
                   "source_manifest": manifest, "loaded_sources": loaded,
                   "request_replay_sha256": report["request_replay_sha256"],
                   "journal_replay_sha256": report["journal_replay_sha256"]}
        (run / "run_receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        print((run / "proof_report.txt").read_text(encoding="utf-8"), end="")
        print(f"Reports: {run}")
        print("Finished. This command returns to its prompt.")
        return 0
    except Exception:
        detail = traceback.format_exc()
        print("Restriction and demotion policy proof: FAILED\n" + detail, file=sys.stderr)
        if run is not None:
            (run / "failure.txt").write_text(detail, encoding="utf-8")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
