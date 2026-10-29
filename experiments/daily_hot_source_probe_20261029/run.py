"""Focused offline source clock correction and SQLite evidence probe."""
from contextlib import closing
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import sys
import time
import unittest
from uuid import uuid4

ROOT=Path(__file__).resolve().parent
NATIVE='5552c5db43351d1a9ae8d376196cc99ba9c7f05d'
CHANGED=['src/mb_watchlist_coordinator/daily_feed_worker.py',
    'src/mb_watchlist_coordinator/nasdaq_recovery_supervisor.py']


def inventory():
    manifest=json.loads((ROOT/'SOURCE_INVENTORY.json').read_text())
    if (manifest['contract']!='daily-hot-source-probe-source-v1'
            or manifest['source']['market_data_commit']!=NATIVE
            or manifest['runtime_changes_since_diagnostic']!=CHANGED):
        raise ValueError('Focused source probe contract differs')
    actual={p.relative_to(ROOT).as_posix() for p in ROOT.rglob('*') if p.is_file()
        and p.relative_to(ROOT).parts[0]!='runs' and p!=ROOT/'SOURCE_INVENTORY.json'}
    if actual!=set(manifest['files']):raise ValueError('Source set differs')
    for name,sha in manifest['files'].items():
        p=ROOT/name
        if p.is_symlink() or not p.resolve().is_relative_to(ROOT) or hashlib.sha256(p.read_bytes()).hexdigest()!=sha:
            raise ValueError('Source bytes differ')
    return manifest


def saved_owner_evidence(run):
    from mb_watchlist_coordinator.daily_supervision import unseal
    from mb_watchlist_coordinator.nasdaq_recovery_supervisor import _failure_details
    base=run/'owner';state=base/'daily_hot_test';out={'read_errors':[]}
    for name in ('driver-state.json','hot-status.json'):
        p=state/name
        if p.exists():out[name]=unseal(json.loads(p.read_text()))
    p=base/'daily_outer_test/operating-result.json'
    out['owner']=unseal(json.loads(p.read_text())) if p.exists() else None
    statements={
        'daily-feed.sqlite3':('SELECT payload FROM feed_event ORDER BY sequence', 'feed_events'),
        'daily-source.sqlite3':('SELECT payload FROM recovery_supervisor_event ORDER BY sequence DESC LIMIT 3','recent_source_events'),
        'publication.sqlite3':('SELECT payload FROM publication_event ORDER BY sequence','publication_events')}
    for name,(sql,key) in statements.items():
        p=state/name
        if not p.exists():continue
        try:
            with closing(sqlite3.connect(p.resolve().as_uri()+'?mode=ro',uri=True)) as c:
                out[key]=[json.loads(row[0]) for row in c.execute(sql)]
            if key=='publication_events':
                out[key]=[{'kind':e['kind'],'plan_id':e.get('plan_id'),
                    'request_sequence':e.get('request_sequence'),
                    'revision':e.get('proposal',e.get('journal_receipt',{}).get('proposal',{})).get('revision')}
                    for e in out[key]]
        except sqlite3.Error as error:
            out['read_errors'].append({'file':str(p),'type':type(error).__name__,**_failure_details(error)})
    feeds=out.get('feed_events',[])
    out['valid_feed_attempts']=sum(e.get('outcome',{}).get('status')=='valid' for e in feeds)
    out['unavailable_feed_attempts']=sum(e.get('outcome',{}).get('status')=='unavailable' for e in feeds)
    journals=list(base.glob('quote_observation_journal_v2_api_opening_*/*.sqlite3'))
    journals=[p for p in journals if not p.name.endswith('.hot.poller.sqlite3')]
    if len(journals)==1:
        try:
            with closing(sqlite3.connect(journals[0].resolve().as_uri()+'?mode=ro',uri=True)) as c:
                out['native_hot_acquisitions']=c.execute("SELECT count(*) FROM quote_acquisition WHERE channel='hot'").fetchone()[0]
        except sqlite3.Error as error:
            out['read_errors'].append({'file':str(journals[0]),'type':type(error).__name__,**_failure_details(error)})
    return out


def verify(manifest):
    def denied(*args,**kwargs):raise OSError('Network denied in focused source probe')
    socket.socket.connect=socket.socket.connect_ex=socket.create_connection=socket.getaddrinfo=denied
    run=ROOT/'runs'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ_')+uuid4().hex[:8])
    run.mkdir(parents=True,exist_ok=False)
    os.environ['MB_DAILY_OPERATING_OWNER_DIR']=str(run/'owner')
    names=['test_daily_feed','test_source_diagnostics',
        'test_daily_operating.DailyOperatingTests.test_complete_collection_proof_preserves_native_journal_and_never_reports_in_the_active_scope']
    print('OFFLINE source clock correction and SQLite evidence probe. No password, API or production changes.',flush=True)
    print('18 focused checks, including one owned collection run. Prior recovery/capacity drills are not repeated. Allow about 15 seconds.',flush=True)
    began=time.monotonic()
    with (run/'tests.log').open('w',encoding='utf-8') as stream:
        result=unittest.TextTestRunner(stream=stream,verbosity=1).run(unittest.defaultTestLoader.loadTestsFromNames(names))
    print((run/'tests.log').read_text(),flush=True)
    inventory()
    evidence=saved_owner_evidence(run);owner=evidence.get('owner')
    passed=bool(result.wasSuccessful() and result.testsRun==18 and not result.skipped
        and owner and owner['result']=='STOPPED' and owner['stop_reason']=='operator_stop'
        and owner['cleanup']['status']=='EXIT_OBSERVED' and owner['reporting']['status']=='COMPLETE'
        and owner['reporting']['native_audit_passed'] and owner['reporting']['two_fresh_replays_equal']
        and evidence.get('native_hot_acquisitions')==2 and evidence['valid_feed_attempts']>=1
        and evidence['unavailable_feed_attempts']==0 and not evidence['read_errors'])
    report={'contract':'daily-hot-source-clock-and-diagnostics-probe-v1',
        'result':'PASS' if passed else 'FAILED','scope':'focused offline correction and one owned synthetic collection run',
        'tests':result.testsRun,'passed':result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped),
        'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),
        'failed_tests':[test.id() for test,error in result.failures+result.errors],
        'seconds':time.monotonic()-began,'source':manifest['source'],
        'platform':sys.platform,'python':list(sys.version_info[:3]),'sqlite_version':sqlite3.sqlite_version,
        'windows_checks_passed':bool(passed and os.name=='nt'),
        'network':'denied','actual_vault_access':False,'actual_broker_sdk_used':False,
        'production_changes':False,'production_hot_enabled':False,'live_launch_available':False,
        'proposed_values_adopted':False,'full_day_capacity_qualified':False,'provider_capacity_qualified':False,
        'prior_windows_command_63_result':'FAILED','prior_windows_command_64_result':'FAILED',
        'prior_windows_recovery_component':'PASS; forced lease/exit gap; 15.029873-second hold',
        'prior_capacity_component_retained':True,'prior_recovery_and_capacity_repeated':False,
        'original_windows_io_error_cause_resolved':False,
        'additional_local_publication_prefix_block_cause_resolved':False,
        'operating_release_qualified':False,
        'original_windows_io_error_note':'Original file/operation/extended code was not recorded. A passing probe does not identify that past cause.',
        'owned_source_evidence':evidence,
        'remaining':['Windows source probe result and actual CMD prompt return',
            'Investigate any recurring SQLite failure using its retained code/origin; original transient I/O cause remains unassigned',
            'Investigate the additional intermittent local publication-prefix block; passing runs do not erase it',
            'Provider capacity and concrete deployment/rollback/settings/activation review',
            'Controlled live automatic Hot, then manual membership and read-only Overlay']}
    (run/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2),flush=True)
    print('Saved report:',run/'verification.json',flush=True)
    return 0 if passed else 1


def main():
    manifest=inventory();sys.dont_write_bytecode=True;os.environ['PYTHONDONTWRITEBYTECODE']='1'
    sys.path[:0]=[str(ROOT/'coordinator/src'),str(ROOT/'market_data/src'),str(ROOT/'coordinator/tests')]
    if sys.argv[1:]==['verify']:return verify(manifest)
    return 64


if __name__=='__main__':
    try:raise SystemExit(main())
    except (OSError,ValueError,KeyError,TypeError) as error:
        print('Focused source probe refused:',type(error).__name__,str(error),flush=True)
        raise SystemExit(70)
