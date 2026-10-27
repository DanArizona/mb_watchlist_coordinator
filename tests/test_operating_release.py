import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[1]/"experiments/hot_operating_foundation_20261027/release.py"
spec = importlib.util.spec_from_file_location("operating_release_under_test", PATH)
release = importlib.util.module_from_spec(spec); spec.loader.exec_module(release)


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.package = Path(self.temp.name)
        (self.package/"entry.py").write_text("# synthetic\n")
        self.manifest = {"contract": "hot-operating-foundation-release-v1", "hot_enabled": False,
                         "runtime_sha256": {"entry.py": release.sha(self.package/"entry.py")}}
        (self.package/"RELEASE.json").write_text(json.dumps(self.manifest))

    def test_changed_or_extra_executable_content_is_refused(self):
        self.assertEqual(release.load_manifest(self.package), self.manifest)
        (self.package/"extra.py").write_text("# unlisted\n")
        with self.assertRaises(ValueError): release.load_manifest(self.package)
        (self.package/"extra.py").unlink()
        (self.package/"entry.py").write_text("# changed\n")
        with self.assertRaises(ValueError): release.load_manifest(self.package)

    def test_bytecode_is_not_an_inventory_bypass(self):
        (self.package/"entry.pyc").write_bytes(b"not executable; synthetic test")
        with self.assertRaises(ValueError): release.load_manifest(self.package)

    def test_windows_acceptance_is_bound_to_this_exact_manifest(self):
        self.manifest["source_commit"] = "a"*40
        marker = {"windows_accepted": True, "result": "PASS", "skipped": 0, "failures": 0,
                  "errors": 0, "release_sha256": release.sha(self.package/"RELEASE.json"),
                  "market_data_source_commit": "a"*40}
        (self.package/"ACCEPTED.json").write_text(json.dumps(marker))
        self.assertTrue(release.windows_qualification(self.manifest, self.package))
        marker["skipped"] = 1
        (self.package/"ACCEPTED.json").write_text(json.dumps(marker))
        self.assertFalse(release.windows_qualification(self.manifest, self.package))

    def test_unapproved_install_and_wrong_platform_stop_before_writes(self):
        before = sorted(p.name for p in self.package.iterdir())
        with self.assertRaisesRegex(ValueError, "approval"):
            release.apply(self.package, self.manifest, approved=False)
        with patch.object(release, "os", SimpleNamespace(name="posix")):
            with self.assertRaisesRegex(ValueError, "Windows"):
                release.validate_idle(self.package)
        self.assertEqual(sorted(p.name for p in self.package.iterdir()), before)


class SourceStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        def git(*args):
            return subprocess.check_output(["git", "-c", "user.name=Synthetic Test", "-c",
                "user.email=synthetic@example.invalid", "-C", str(self.root), *args],
                stderr=subprocess.DEVNULL, text=True).strip()
        self.git = git
        git("init", "-b", "main")
        (self.root/"a.py").write_text("# baseline\n")
        baseline = release.sha(self.root/"a.py")
        git("add", "a.py"); git("commit", "-m", "synthetic baseline")
        base = git("rev-parse", "HEAD")
        git("switch", "-c", "experiment/synthetic")
        (self.root/"a.py").write_text("# candidate\n")
        (self.root/"b.py").write_text("# new source\n")
        candidate = {p: release.sha(self.root/p) for p in ("a.py", "b.py")}
        git("add", "a.py", "b.py"); git("commit", "-m", "synthetic candidate")
        self.manifest = {"baseline_commit": base, "source_commit": git("rev-parse", "HEAD"),
                         "baseline_sha256": {"a.py": baseline, "b.py": None},
                         "candidate_sha256": candidate}
        git("switch", "main")

    def test_unrelated_untracked_files_are_preserved_and_do_not_block_review(self):
        p = self.root/"operator-notes.txt"; p.write_text("synthetic notes\n")
        before = p.read_bytes()
        self.assertEqual(release.check_source(self.root, self.manifest)["head"], self.manifest["baseline_commit"])
        self.assertEqual(p.read_bytes(), before)

    def test_colliding_untracked_and_tracked_edits_are_refused_without_deletion(self):
        collision = self.root/"b.py"; collision.write_text("# preserve this\n")
        with self.assertRaisesRegex(ValueError, "collides"):
            release.check_source(self.root, self.manifest)
        self.assertEqual(collision.read_text(), "# preserve this\n")
        collision.unlink()
        (self.root/"a.py").write_text("# preserve tracked edit\n")
        with self.assertRaisesRegex(ValueError, "Tracked"):
            release.check_source(self.root, self.manifest)

    def test_wrong_head_or_branch_is_refused(self):
        self.git("switch", "experiment/synthetic")
        with self.assertRaisesRegex(ValueError, "main"):
            release.check_source(self.root, self.manifest)
        self.git("switch", "main")
        wrong = dict(self.manifest, baseline_commit="0"*40)
        with self.assertRaisesRegex(ValueError, "HEAD"):
            release.check_source(self.root, wrong)


if __name__ == "__main__": unittest.main()
