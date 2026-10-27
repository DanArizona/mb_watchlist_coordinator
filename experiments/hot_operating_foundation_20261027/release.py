"""Source-pinned, after-close cadence installation and reversible Git rollback.

Review/qualification are read-only with respect to production. Install/revert
are separate explicitly approved production operations; no journal is edited.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4
from zoneinfo import ZoneInfo

PACKAGE = Path(__file__).resolve().parent
TEXT_SUFFIXES = {".py", ".cmd", ".json", ".md", ".txt", ".toml", ".css", ".js", ".svg"}


def sha(path: Path) -> str:
    content = path.read_bytes()
    if path.suffix in TEXT_SUFFIXES:
        content = content.replace(b"\r\n", b"\n")
    return hashlib.sha256(content).hexdigest()


def load_manifest(package: Path | None = None) -> dict:
    package = PACKAGE if package is None else Path(package)
    manifest = json.loads((package/"RELEASE.json").read_text())
    if manifest["contract"] != "hot-operating-foundation-release-v1" or manifest["hot_enabled"] is not False:
        raise ValueError("Unexpected release contract or Hot activation")
    for relative, expected in manifest["runtime_sha256"].items():
        path = package/relative
        if (not path.resolve().is_relative_to(package.resolve()) or path.is_symlink()
                or not path.is_file() or sha(path) != expected):
            raise ValueError("Source inventory mismatch: "+relative)
    actual = {str(p.relative_to(package)).replace("\\", "/") for p in package.rglob("*")
              if p.is_file() and p.suffix in {".py", ".pyc", ".cmd", ".ps1", ".pyd", ".dll"}
              and p.relative_to(package).parts[0] != "runs"}
    if actual-set(manifest["runtime_sha256"]):
        raise ValueError("Unlisted executable source or bytecode in release")
    return manifest


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "--no-pager", "-C", str(root), *args],
                                   text=True, stderr=subprocess.STDOUT).strip()


def check_source(root: Path, manifest: dict, *, installed: bool = False, package: Path | None = None) -> dict:
    package = PACKAGE if package is None else Path(package)
    if git(root, "branch", "--show-current") != "main":
        raise ValueError("Production source must be on main for installation or rollback")
    head = git(root, "rev-parse", "HEAD")
    expected_head = manifest["source_commit"] if installed else manifest["baseline_commit"]
    if head != expected_head:
        raise ValueError("Production HEAD differs from the reviewed source baseline")
    if git(root, "status", "--porcelain", "--untracked-files=no"):
        raise ValueError("Tracked local edits must be preserved and reviewed before deployment")
    targets = manifest["candidate_sha256"] if installed else manifest["baseline_sha256"]
    for relative, fingerprint in targets.items():
        path = root/relative
        if not path.resolve().is_relative_to(root.resolve()) or path.is_symlink():
            raise ValueError("Source target escapes its root")
        if fingerprint is None:
            if path.exists():
                raise ValueError("Untracked file collides with a new release source path: "+relative)
        elif not path.is_file() or sha(path) != fingerprint:
            raise ValueError("Source target differs from reviewed bytes: "+relative)
    return {"head": head, "tracked_edits": False, "source_targets": len(targets),
            "unrelated_untracked_files": "preserved; not a deployment blocker"}


def windows_qualification(manifest: dict, package: Path | None = None) -> bool:
    package = PACKAGE if package is None else Path(package)
    try:
        marker = json.loads((package/"ACCEPTED.json").read_text())
        return bool(marker["windows_accepted"] is True and marker["result"] == "PASS"
                    and marker["skipped"] == marker["failures"] == marker["errors"] == 0
                    and marker["release_sha256"] == sha(package/"RELEASE.json")
                    and marker["market_data_source_commit"] == manifest["source_commit"])
    except (OSError, ValueError, KeyError, TypeError):
        return False


def validate_idle(root: Path) -> None:
    if os.name != "nt":
        raise ValueError("Production changes require the Windows production host")
    if datetime.now(ZoneInfo("America/New_York")).hour < 16:
        raise ValueError("Apply after 16:00 ET, after closeout and monitor shutdown")
    from mb_market_data.acquisition_health import windows_process_inventory
    inventory = windows_process_inventory()
    if not inventory["known"]:
        raise ValueError("Production change refused: process inventory is unknown")
    for process in inventory["processes"]:
        argv = process["argv"]
        names = {Path(a.replace("\\", "/")).name.lower() for a in argv}
        if ("probe_universe_quote_watch.py" in names
                or names & {"polling_health.py", "run_packet.py"} and "monitor" in argv):
            raise ValueError(f"Wait for poller/monitor shutdown; active PID {process['pid']}")


def review(root: Path, manifest: dict) -> dict:
    return {"contract": "cadence-deployment-review-v1", "source": check_source(root, manifest),
            "windows_qualified": windows_qualification(manifest),
            "baseline_commit": manifest["baseline_commit"], "candidate_commit": manifest["source_commit"],
            "changes": list(manifest["candidate_sha256"]), "production_changes_performed": False,
            "cadence_profile": "interleaved-v1 (explicit opt-in; default remains legacy-v1)",
            "hot_enabled": False,
            "next": "After Windows PASS and explicit approval, install after closeout with all production pollers/Health stopped."}


def apply(root: Path, manifest: dict, *, approved: bool, rollback: bool = False) -> Path:
    if not approved:
        raise ValueError("Separate explicit production-change approval is required")
    if not windows_qualification(manifest):
        raise ValueError("Windows offline qualification is required before a production change")
    from mb_market_data.acquisition_health import operation_lock
    with operation_lock("hot-operating-source-deployment:"+str(root.resolve()).casefold()):
        validate_idle(root)
        check_source(root, manifest, installed=rollback)
        before = git(root, "rev-parse", "HEAD")
        if not rollback:
            bundle = PACKAGE/"market-data-cadence.bundle"
            git(root, "bundle", "verify", str(bundle))
        directory = root/"output/hot_operating_deployment"/(
            datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ_")+uuid4().hex[:8])
        directory.mkdir(parents=True, exist_ok=False)
        receipt_path = directory/"deployment.json"
        receipt = {"operation": "rollback" if rollback else "install", "state": "PREPARED",
                   "before_commit": before, "source_commit": manifest["source_commit"],
                   "production_hot_enabled": False, "journals_modified": False}
        def save():
            from mb_market_data.acquisition_health import atomic_json
            atomic_json(receipt_path, receipt)
        save()
        try:
            if rollback:
                git(root, "revert", "--no-edit", manifest["source_commit"])
            else:
                git(root, "fetch", str(PACKAGE/"market-data-cadence.bundle"), manifest["source_branch"])
                # The OS-owned operation lock and immediate second guard cover
                # competing launches; no reset, checkout overwrite or force is used.
                check_source(root, manifest)
                git(root, "merge", "--ff-only", manifest["source_commit"])
            expected = manifest["baseline_sha256"] if rollback else manifest["candidate_sha256"]
            for relative, fingerprint in expected.items():
                path = root/relative
                if fingerprint is None:
                    if path.exists(): raise ValueError("Rollback left a new source target")
                elif sha(path) != fingerprint:
                    raise ValueError("Installed source verification failed: "+relative)
            receipt.update(state="ROLLED_BACK" if rollback else "INSTALLED", after_commit=git(root, "rev-parse", "HEAD"))
        except Exception as error:
            receipt.update(state="INCOMPLETE", error_type=type(error).__name__)
            raise
        finally:
            save()
    return receipt_path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("review", "install", "rollback"))
    parser.add_argument("--market-data-root", type=Path, required=True)
    parser.add_argument("--production-change-approved", action="store_true")
    args = parser.parse_args(argv)
    try:
        manifest = load_manifest()
        sys.path.insert(0, str(PACKAGE/"market_data/src"))
        root = args.market_data_root.resolve()
        if args.operation == "review":
            print(json.dumps(review(root, manifest), indent=2))
        else:
            print("Deployment receipt:", apply(root, manifest, approved=args.production_change_approved,
                                                rollback=args.operation == "rollback"))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"Cadence release STOPPED: {error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
