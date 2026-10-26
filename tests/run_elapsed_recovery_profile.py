"""Elapsed owned-worker recovery proof with synthetic APIs and original limits."""
from datetime import datetime,timezone
import argparse
import hashlib
import json
from pathlib import Path
import socket
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests'),
    str(ROOT/'experiments/sampling_promotion_20261016/market_data/src'),
    str(ROOT/'experiments/authenticated_startup_20261023/reference_mb_tools/src')]
from live_profile_fixtures import config,Clock,SECRET
from mb_watchlist_coordinator.authenticated_startup import SessionPassword
from mb_watchlist_coordinator.live_profile import validate_configuration,stop_request
from mb_watchlist_coordinator.outer_harness import OuterHarness,OuterSchedule
from mb_watchlist_coordinator.sampling_requests import timestamp


def main():
    p=argparse.ArgumentParser();p.add_argument('--output-root',type=Path,required=True);args=p.parse_args()
    def denied(*a,**kw):raise RuntimeError('Network denied in elapsed recovery proof')
    socket.socket.connect=socket.socket.connect_ex=socket.create_connection=socket.getaddrinfo=denied
    root=args.output_root.resolve();root.mkdir(parents=True,exist_ok=False)
    names=json.loads((ROOT/'experiments/live_profile_recovery_fix_20261026/accepted_before_recovery_sha256.json').read_text())
    source={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in names}
    value,path,sha=config(root,'owned_worker_recovery');clock=Clock(value['settings']['password_submitted_at_utc'])
    plan=validate_configuration(value,sha,verify_source=lambda *a:None)
    harness=OuterHarness(Path(value['outer_root']),OuterSchedule(plan.settings.password_submitted_at_utc,
        plan.public['start_at_utc'],plan.public['stop_at_utc']),value['nonce'],clock=clock,
        expected_preflight_sha256=plan.configuration_sha256)
    probe=ROOT/'tests/fixtures/boundary_profile_probe.py'
    def command(role):return (sys.executable,'-I','-B',str(probe),role,str(path),sha)
    secret=SessionPassword(SECRET,sha);frame=secret.frame(value['nonce']);secret.close()
    began=time.monotonic();last=[began-30]
    def stopping():
        if time.monotonic()-last[0]>=15:
            print('Elapsed synthetic recovery profile: '+str(round(time.monotonic()-began,1))+'s',flush=True)
            last[0]=time.monotonic()
        return stop_request(value,sha) is not None or time.monotonic()-began>=390
    result=harness.run(command('controller'),reporter_command=command('report'),
        credential_frame=frame,stop_requested=stopping)
    report=json.loads((Path(value['outer_root'])/'native-profile-report.json').read_text())
    runtime=Path(value['settings']['experiment_root'])
    stopped=json.loads((runtime/'runtime-stop.json').read_text()) if (runtime/'runtime-stop.json').exists() else None
    profile=json.loads((runtime/'profile.json').read_text());events={e['kind']:e['data'] for e in profile['events']}
    same=source=={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in names}
    missing=set(report['missing_slot_ids']);explained=set(report['intentional_outage_missing_slot_ids'])
    fault,restart=events.get('fault'),events.get('restart')
    hold=(timestamp(restart['started_at_utc'])-timestamp(fault['exit_observed_at_utc'])).total_seconds() if fault and restart else None
    prepared=bool(restart and timestamp(restart['ready_at_utc'])<timestamp(restart['first_eligible_slot_utc']))
    checks={'source_unchanged':same,'profile_goal':result['stop_reason']=='profile_goal',
        'profile_verdict':result['result']=='PASS_WITH_WARNINGS','goals':report['goals']['goal_complete']
            and report['goals']['before_fault']>=12 and report['goals']['after_restart']>=24,
        'source_reconciled':report['source_reconciled'],'two_equal_replays':report['identical_fresh_replays'],
        'intentional_raw_outage_retained':bool(missing) and not report['raw_native_audit_passed'] and missing==explained,
        'no_unexplained_slots':not report['unexplained_missing_slot_ids'],
        'all_valid_acknowledged':not report['non_quote_acquisition_ids'] and not report['unacknowledged_acquisition_ids'],
        'original_full_hold':hold is not None and hold>=15,'prepared_before_declared_first_slot':prepared,
        'controller_stop_receipt':bool(stopped and stopped['counts_verified'] and 'stop' in events),
        'original_cumulative_permits':bool(stopped and stopped['hot_quote_permits']<=60 and stopped['identity_quote_permits']<=3),
        'owned_scopes_empty':all(result[n]['scope_empty_observed'] for n in ('cleanup','reporter_cleanup')),
        'cooperative_controller_exit':not result['cleanup']['forced'] and result['cleanup']['controller_returncode']==0,
        'separate_read_only_report_complete':result['reporting_complete'] and report['reporting_read_only']}
    evidence={'result':'PASS' if all(checks.values()) else 'FAILED','seconds':time.monotonic()-began,
        'checks':checks,'source_sha256':source,'source_unchanged_during_proof':same,
        'scope':'Full elapsed original >=60s preparation, frozen 720s window, >=60s completed-at feed pacing, native cadence and 15s hold. Synthetic credential/directory/feed/quote APIs only; actual owned authenticated fault/replacement, unchanged raw native audit and two fresh replays. Fixed date/time offset; no compressed durations or logical jumps. Not live-provider/production qualification.',
        'network':'denied','actual_vault_access':False,'production_access':False,
        'outer':result,'native_report':report,'runtime_stop':stopped,'hold_seconds':hold,
        'replacement_prepared_before_first_slot':prepared}
    (root/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n')
    from saved_artifact_scan import scan_saved_artifacts
    scan_saved_artifacts(root,(SECRET.encode(),))
    print(json.dumps({'result':evidence['result'],'seconds':evidence['seconds'],'checks':checks,
        'goals':report['goals'],'missing_slot_ids':report['missing_slot_ids'],
        'unexplained_missing_slot_ids':report['unexplained_missing_slot_ids'],
        'runtime_stop':stopped,'saved':str(root/'evidence.json')},indent=2),flush=True)
    return 0 if all(checks.values()) else 1


if __name__=='__main__':raise SystemExit(main())
