"""Changed probe/launcher paths and accepted credential interface regressions."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import socket
import sys
import time
import unittest
import uuid

ROOT=Path(__file__).resolve().parents[2]
SUITES=('test_authenticated_startup','test_installed_startup_probe','test_installed_probe_launcher')

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output-root',type=Path,required=True)
    args=parser.parse_args()
    def denied(*a,**kw):raise RuntimeError('Network denied in installed-client offline qualification')
    socket.socket.connect=socket.socket.connect_ex=socket.create_connection=socket.getaddrinfo=denied
    sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests'),
        str(ROOT/'experiments/authenticated_startup_20261023/reference_mb_tools/src')]
    started=time.perf_counter()
    tests=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(name) for name in SUITES)
    result=unittest.TextTestRunner(verbosity=1).run(tests)
    report={'result':'PASS' if result.wasSuccessful() else 'FAILED','tests':result.testsRun,
        'passed':result.testsRun-len(result.skipped)-len(result.failures)-len(result.errors),
        'skipped':len(result.skipped),'failures':len(result.failures),'errors':len(result.errors),
        'seconds':time.perf_counter()-started,'network':'denied','production_access':False,
        'scope':'Changed installed-client probe/launcher plus accepted credential interface regressions; synthetic encrypted configuration/SDK and owned process deadline/redaction drills only',
        'installed_sdk_or_live_authentication_qualified':False,'prior_command38_unchanged':True,'suites':list(SUITES)}
    folder=args.output_root/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]);folder.mkdir(parents=True,exist_ok=False)
    (folder/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2));print('Saved report:',folder/'verification.json')
    return 0 if result.wasSuccessful() else 1

if __name__=='__main__':raise SystemExit(main())
