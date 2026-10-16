"""Self-contained, non-interactive proof. All writes stay under this bundle."""

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


def verify_bundle(root: Path) -> dict:
    root = root.resolve()
    manifest = json.loads((root / "bundle_manifest.json").read_text(encoding="utf-8"))
    for relative, expected in manifest["files_sha256"].items():
        path = (root / relative).resolve()
        if not path.is_relative_to(root):
            raise ValueError(f"Manifest path escapes the review bundle: {relative}")
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Bundle file differs from the reviewed payload: {relative}")
    return manifest


def main() -> int:
    sys.dont_write_bytecode = True
    root = Path(__file__).resolve().parent
    run_directory = None
    try:
        if len(sys.argv) != 1:
            raise ValueError("This proof accepts no arguments or external journal path")
        manifest = verify_bundle(root)
        print("COORDINATOR PROMOTION PROOF - offline synthetic membership", flush=True)
        print("Uses bundled pinned source; writes a new journal and reports under this folder.", flush=True)
        sys.path[:0] = [str(root / "coordinator" / "src"), str(root / "market_data" / "src"),
                        str(root / "bridge"), str(root)]
        run_root = root / "runs"
        if run_root.resolve().parent != root:
            raise ValueError("runs must be a direct child of the review folder")
        run_root.mkdir(exist_ok=True)
        run_directory = run_root / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8])
        run_directory.mkdir()
        test_scratch = run_directory / "temporary_tests"
        test_scratch.mkdir()
        tempfile.tempdir = str(test_scratch)
        stream = io.StringIO()
        suite = unittest.defaultTestLoader.discover(str(root / "proof_tests"))
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
        test_text = stream.getvalue()
        (run_directory / "test_results.txt").write_text(test_text, encoding="utf-8")
        print(test_text, end="", flush=True)
        if not result.wasSuccessful() or result.testsRun == 0:
            raise RuntimeError("Promotion proof tests failed; see test_results.txt")
        from promotion_proof import run_proof
        report = run_proof(run_directory)
        loaded = {}
        for name, module in tuple(sys.modules.items()):
            if name.startswith(("mb_market_data", "mb_watchlist_coordinator")):
                path = Path(module.__file__).resolve()
                if not path.is_relative_to(root):
                    raise ValueError(f"Imported external source for {name}: {path}")
                loaded[name] = str(path.relative_to(root))
        receipt = {"result": "PASS", "tests_run": result.testsRun,
                   "bundle_id": manifest["bundle_id"], "source_pins": manifest["source_pins"],
                   "loaded_source_files": loaded, "proof_report": "proof_report.json"}
        (run_directory / "run_receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        print((run_directory / "proof_report.txt").read_text(encoding="utf-8"), end="")
        print(f"Reports: {run_directory}")
        print("Finished. This command returns to its prompt.")
        return 0
    except Exception:
        detail = traceback.format_exc()
        print("Coordinator promotion proof: FAILED\n" + detail, file=sys.stderr)
        if run_directory is not None:
            (run_directory / "failure.txt").write_text(detail, encoding="utf-8")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
