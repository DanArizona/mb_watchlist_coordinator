from contextlib import redirect_stdout
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest

HERE=Path(__file__).resolve().parents[1]/'experiments/profile_observer_20261024/launcher.py'
spec=importlib.util.spec_from_file_location('profile_observer_test_launcher',HERE)
launcher=importlib.util.module_from_spec(spec);spec.loader.exec_module(launcher)


class ObserverLauncherTests(unittest.TestCase):
    def run_case(self,mode):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);p=root/'coordinator/experiments/profile_observer_20261024/verify.py';p.parent.mkdir(parents=True)
            p.write_text('''from pathlib import Path
import json,os,sys
root=Path(sys.argv[-1]);folder=root/'controlled';folder.mkdir(parents=True)
mode='''+repr(mode)+'''
if mode!='missing':
 (folder/'verification.json').write_text(json.dumps({'result':'FAILED' if mode=='mismatch' else 'PASS','tests':1,'failures':0,'errors':0}))
with open(os.devnull,'w') as quiet:os.dup2(quiet.fileno(),1)
raise SystemExit(0)
''')
            (root/'SOURCE_INVENTORY.json').write_text(json.dumps({'files':{p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()}}))
            out=io.StringIO()
            with redirect_stdout(out):code=launcher.main(root)
            return code,out.getvalue()

    def test_launcher_prints_saved_report_despite_muted_verifier_stdout(self):
        code,out=self.run_case('pass');self.assertEqual(code,0);self.assertIn('"result": "PASS"',out);self.assertIn('Saved report:',out)

    def test_silent_exit_without_report_cannot_be_pass(self):
        code,out=self.run_case('missing');self.assertEqual(code,70);self.assertIn('report BLOCKED',out)

    def test_exit_and_report_mismatch_cannot_be_pass(self):
        code,out=self.run_case('mismatch');self.assertEqual(code,70);self.assertIn('report BLOCKED',out)
