"""Read-only triage of the specific saved synthetic owner proof. No test rerun."""
import argparse
from contextlib import closing
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from uuid import uuid4

DEFAULT='daily_hot_exit_fix_20261029_7cce5c0_5552c5d/runs/20261029T082857Z_49b9595b/owner/daily_hot_test'


def failure(error,operation):
    return {'operation':operation,'exception':type(error).__name__,'detail':str(error),
        'sqlite_errorcode':getattr(error,'sqlite_errorcode',None),
        'sqlite_errorname':getattr(error,'sqlite_errorname',None),
        'winerror':getattr(error,'winerror',None)}


def inspect_database(path):
    result={'file':str(path),'errors':[]};operation='stat/hash'
    try:
        if path.is_symlink():raise ValueError('Symlink database refused')
        before=hashlib.sha256(path.read_bytes()).hexdigest()
        result['bytes']=path.stat().st_size
        operation='read-only connect'
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=1)) as connection:
            for name,sql in (('journal_mode','PRAGMA journal_mode'),('quick_check','PRAGMA quick_check'),
                    ('tables',"SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")):
                operation=sql
                try:result[name]=[row[0] for row in connection.execute(sql)]
                except (sqlite3.Error,OSError) as error:result['errors'].append(failure(error,operation))
            for table,count in (('recovery_supervisor_event',5),('feed_event',10)):
                if table not in result.get('tables',[]):continue
                operation='read last '+table
                try:
                    result[table]=[json.loads(row[0]) for row in connection.execute(
                        'SELECT payload FROM '+table+' ORDER BY sequence DESC LIMIT ?',(count,))]
                except (sqlite3.Error,OSError,ValueError) as error:result['errors'].append(failure(error,operation))
        operation='post-read hash'
        result['database_bytes_unchanged']=before==hashlib.sha256(path.read_bytes()).hexdigest()
    except (sqlite3.Error,OSError,ValueError) as error:result['errors'].append(failure(error,operation))
    return result


def diagnose(state):
    state=state.resolve(strict=True)
    if state.name!='daily_hot_test' or state.parent.name!='owner' or 'runs' not in state.parts:
        raise ValueError('Only an explicitly saved synthetic owner proof is accepted')
    raw=json.loads((state/'daily-worker.json').read_text())
    if Path(raw['publication']['state_root']).resolve()!=state:
        raise ValueError('Saved configuration does not identify this original owner proof')
    journal=Path(raw['collector']['journal_path']).resolve()
    if journal.parent.parent!=state.parent:
        raise ValueError('Journal must be within this same saved synthetic owner proof')
    required=('requests.sqlite3','publication.sqlite3','live.sqlite3','recovery.sqlite3',
        'delivery.sqlite3','identity.sqlite3','daily-source.sqlite3','daily-feed.sqlite3')
    paths=sorted({state/name for name in required}|set(state.glob('*.sqlite3'))|
        {journal}|set(journal.parent.glob('*.sqlite3')))
    report={'contract':'saved-hot-source-read-only-diagnostic-v1','result':'DIAGNOSTIC_COMPLETE',
        'qualification_result':None,'python':list(sys.version_info[:3]),'sqlite_version':sqlite3.sqlite_version,
        'state_root':str(state),'source_databases_opened_read_only':True,'tests_rerun':False,
        'actual_vault_access':False,'actual_broker_sdk_used':False,'provider_access':False,
        'production_changes':False,'original_error_extended_code_available':False,
        'note':'Current read results cannot reconstruct the missing extended code/operation of a past transient error.',
        'databases':[inspect_database(path) for path in paths]}
    for name in ('driver-state.json','driver-stop.json','hot-status.json'):
        path=state/name
        if path.is_file():report[name]=json.loads(path.read_text())
    report['current_database_issues']=[r['file'] for r in report['databases'] if r['errors']
        or r.get('quick_check')!=['ok'] or not r.get('database_bytes_unchanged')]
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-root',type=Path,default=Path(__file__).resolve().parent.parent/DEFAULT)
    args=parser.parse_args()
    report=diagnose(args.state_root)
    directory=Path(__file__).resolve().parent/'diagnostics'
    directory.mkdir(exist_ok=True)
    output=directory/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ_')+uuid4().hex[:8]+'.json')
    output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2),flush=True)
    print('Saved diagnostic:',output,flush=True)
    return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except (OSError,ValueError,KeyError,TypeError) as error:
        print(json.dumps({'result':'DIAGNOSTIC_REFUSED','exception':type(error).__name__,'detail':str(error)}))
        raise SystemExit(2)
