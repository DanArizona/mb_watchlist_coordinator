import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('installed_probe_launcher',ROOT/'experiments/installed_startup_20261023/launcher.py')
launcher=importlib.util.module_from_spec(spec);spec.loader.exec_module(launcher)

class ProbeLauncherTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup);self.root=Path(temporary.name)
        (self.root/'source.py').write_text('# synthetic fixture\n')
        (self.root/'SOURCE_INVENTORY.json').write_text(json.dumps({'files':{
            'source.py':hashlib.sha256((self.root/'source.py').read_bytes()).hexdigest()}}))
    def test_source_inventory_accepts_only_the_delivered_bytes(self):launcher.verify_inventory(self.root)
    def test_changed_source_is_rejected_before_credential_prompt(self):
        (self.root/'source.py').write_text('# changed\n')
        with self.assertRaises(ValueError):launcher.verify_inventory(self.root)
    def test_added_untracked_source_is_refused(self):
        (self.root/'extra.py').write_text('# unexpected\n')
        with self.assertRaises(ValueError):launcher.verify_inventory(self.root)
    def test_installed_probe_requires_same_package_offline_success(self):
        with self.assertRaises(ValueError):launcher.require_qualification(self.root)
        launcher.write_qualification(self.root);launcher.require_qualification(self.root)
    def test_changed_environment_or_inventory_invalidates_qualification(self):
        launcher.write_qualification(self.root)
        receipt=self.root/'runs/offline_qualified.json';value=json.loads(receipt.read_text())
        value['python_executable']='synthetic-different-interpreter';receipt.write_text(json.dumps(value))
        with self.assertRaises(ValueError):launcher.require_qualification(self.root)

    def test_failed_verification_revokes_an_earlier_success_receipt(self):
        launcher.write_qualification(self.root)
        with patch.object(launcher.sys,'argv',['launcher.py','offline']),patch.object(launcher.subprocess,'call',return_value=1):
            self.assertEqual(launcher.main(self.root),1)
        with self.assertRaises(ValueError):launcher.require_qualification(self.root)
        launcher.write_qualification(self.root)
        p=self.root/'SOURCE_INVENTORY.json';p.write_text(p.read_text()+'\n')
        with self.assertRaises(ValueError):launcher.require_qualification(self.root)
