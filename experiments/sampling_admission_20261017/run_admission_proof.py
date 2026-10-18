"""One bounded offline review; no external source installation or arguments."""
from __future__ import annotations
import hashlib
import io
import json
import sys
import tempfile
import traceback
import unittest
import uuid
from datetime import datetime,timezone
from pathlib import Path


def verify_sources(root,experiment):
    manifest=json.loads((experiment/'source_manifest.json').read_text(encoding='utf-8'))
    for name,expected in manifest['files_sha256_lf'].items():
        path=(root/name).resolve()
        if not path.is_relative_to(root) or not path.is_file():raise ValueError('Missing/invalid review source: '+name)
        if hashlib.sha256(path.read_bytes().replace(b'\r\n',b'\n')).hexdigest()!=expected:
            raise ValueError('Source differs from review: '+name)
    return manifest


def main():
    sys.dont_write_bytecode=True
    experiment=Path(__file__).resolve().parent;root=experiment.parent.parent;run=None
    try:
        if len(sys.argv)!=1:raise ValueError('This offline review accepts no external arguments or databases')
        manifest=verify_sources(root,experiment)
        run=experiment/'runs'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8])
        run.mkdir(parents=True)
        sys.path[:0]=[str(root/'src'),str(root/'tests'),str(experiment),str(root/'experiments/hot_acquisition_20261017')]
        temporary=run/'temporary_tests';temporary.mkdir();tempfile.tempdir=str(temporary)
        stream=io.StringIO()
        class Tee:
            def write(self,value):sys.stderr.write(value);stream.write(value)
            def flush(self):sys.stderr.flush()
        suite=unittest.TestSuite()
        for module in ('test_sampling_admission','test_admission_publication'):
            suite.addTests(unittest.defaultTestLoader.loadTestsFromName(module))
        print('[1/3] Admission, policy, publication and acquisition tests.',flush=True)
        result=unittest.TextTestRunner(verbosity=2,stream=Tee()).run(suite)
        (run/'test_results.txt').write_text(stream.getvalue(),encoding='utf-8')
        if not result.wasSuccessful():raise RuntimeError('Admission tests failed; see test_results.txt')
        print('[2/3] Synthetic Nasdaq delivery/retry and first Hot acquisition (logical clock).',flush=True)
        from admission_proof import run_proof
        report=run_proof(run)
        loaded={}
        for name,module in tuple(sys.modules.items()):
            if name.startswith(('mb_market_data','mb_watchlist_coordinator')):
                path=Path(module.__file__).resolve()
                if not path.is_relative_to(root):raise ValueError('External package source imported: '+name)
                loaded[name]=str(path.relative_to(root))
        receipt={'result':'PASS','focused_tests':result.testsRun,'source_manifest':manifest,'loaded_sources':loaded,
                 'journal_replay_sha256':report['journal_replay_sha256'],'request_replay_sha256':report['request_replay_sha256']}
        (run/'run_receipt.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
        print((run/'proof_report.txt').read_text(encoding='utf-8'),end='')
        print('Reports:',run);print('Finished. This command returns to its prompt.');return 0
    except Exception:
        detail=traceback.format_exc();print('Outside-Uni admission proof: FAILED\n'+detail,file=sys.stderr)
        if run is not None:(run/'failure.txt').write_text(detail,encoding='utf-8')
        return 1


if __name__=='__main__':raise SystemExit(main())
