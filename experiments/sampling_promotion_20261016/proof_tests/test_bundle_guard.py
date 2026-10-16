import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from run_offline_proof import verify_bundle


class BundleGuardTests(unittest.TestCase):
    def test_modified_payload_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            payload = root / "payload.py"
            payload.write_bytes(b"original\n")
            manifest = {"files_sha256": {"payload.py": hashlib.sha256(payload.read_bytes()).hexdigest()}}
            (root / "bundle_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            verify_bundle(root)
            payload.write_bytes(b"modified\n")
            with self.assertRaisesRegex(ValueError, "differs"):
                verify_bundle(root)

    def test_manifest_cannot_read_outside_bundle(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "bundle_manifest.json").write_text(
                json.dumps({"files_sha256": {"../outside.py": "untrusted"}}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "escapes"):
                verify_bundle(root)
