"""Noninteractive, bounded Hot review using only its bundled pinned source."""
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
        p=(root/name).resolve()
        if not p.is_relative_to(root) or not p.is_file():raise ValueError('Missing/invalid review source: '+name)
        if hashlib.sha256(p.read_bytes().replace(b'\r\n',b'\n')).hexdigest()!=expected:raise ValueError('Source differs from review: '+name)
    return manifest


def main():
    sys.dont_write_bytecode=True
    experiment=Path(__file__).resolve().parent;root=experiment.parent.parent;run=None
    try:
        if len(sys.argv)!=1:raise ValueError('This offline review accepts no external arguments or databases')
        manifest=verify_sources(root,experiment)
        sys.path[:0]=[str(root/'src'),str(root/'experiments/sampling_promotion_20261016/market_data/src'),str(experiment)]
        runs=experiment/'runs'
        if runs.resolve().parent!=experiment:raise ValueError('runs must stay within this experiment')
        runs.mkdir(exist_ok=True)
        run=runs/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]);run.mkdir()
        temp=run/'temporary_tests';temp.mkdir();tempfile.tempdir=str(temp)
        print('ISOLATED HOT ACQUISITION - synthetic quote source; no API/password/production write',flush=True)
        suite=unittest.TestLoader().discover(str(experiment),pattern='test_hot_acquisition.py')
        output=io.StringIO();result=unittest.TextTestRunner(stream=output,verbosity=2).run(suite)
        (run/'test_results.txt').write_text(output.getvalue(),encoding='utf-8');print(output.getvalue(),end='',flush=True)
        if result.testsRun!=30 or not result.wasSuccessful():raise RuntimeError('Expected all 30 focused tests to pass')
        from hot_proof import run_proof
        report=run_proof(run)
        loaded={}
        for name,module in tuple(sys.modules.items()):
            if name.startswith(('mb_market_data','mb_watchlist_coordinator')):
                p=Path(module.__file__).resolve()
                if not p.is_relative_to(root):raise ValueError('External package source imported: '+name)
                loaded[name]=str(p.relative_to(root))
        receipt={'result':'PASS','focused_tests':result.testsRun,'source_manifest':manifest,'loaded_sources':loaded,
                 'journal_replay_sha256':report['journal_replay_sha256'],'metrics':report['metrics']}
        (run/'run_receipt.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
        print((run/'proof_report.txt').read_text(encoding='utf-8'),end='')
        print('Reports:',run);print('Finished. This command returns to its prompt.')
        return 0
    except Exception:
        detail=traceback.format_exc();print('Isolated Hot acquisition proof: FAILED\n'+detail,file=sys.stderr)
        if run is not None:(run/'failure.txt').write_text(detail,encoding='utf-8')
        return 1


if __name__=='__main__':raise SystemExit(main())
