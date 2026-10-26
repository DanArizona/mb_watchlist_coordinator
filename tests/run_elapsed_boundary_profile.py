"""One affected elapsed ordinary proof; synthetic providers, original pacing."""
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
from mb_watchlist_coordinator.live_profile import validate_configuration
from mb_watchlist_coordinator.outer_harness import OuterHarness,OuterSchedule

def main():
    p=argparse.ArgumentParser();p.add_argument('--output-root',type=Path,required=True);args=p.parse_args()
    def denied(*a,**kw):raise RuntimeError('Network denied in elapsed boundary proof')
    socket.socket.connect=socket.socket.connect_ex=socket.create_connection=socket.getaddrinfo=denied
    root=args.output_root.resolve();root.mkdir(parents=True,exist_ok=False)
    paths=['src/mb_watchlist_coordinator/'+name+'.py' for name in
        ('integrated_catalog','integrated_runtime','live_profile','live_profile_entry','profile_runtime')]
    source={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in paths}
    value,path,sha=config(root);clock=Clock(value['settings']['password_submitted_at_utc'])
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
            elapsed=time.monotonic()-began
            print('Elapsed synthetic ordinary profile: '+str(round(elapsed,1))+'s',flush=True);last[0]=time.monotonic()
        return time.monotonic()-began>=330
    result=harness.run(command('controller'),reporter_command=command('report'),
        credential_frame=frame,stop_requested=stopping)
    report=json.loads((Path(value['outer_root'])/'native-profile-report.json').read_text())
    same_source=source=={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in paths}
    passed=bool(same_source and result['result'] in ('PASS','PASS_WITH_WARNINGS')
        and report['raw_native_audit_passed'] and report['goals']['goal_complete']
        and report['goals']['after_cutover']>=30 and report['identical_fresh_replays']
        and not report['missing_slot_ids'] and result['cleanup']['status']=='EXIT_OBSERVED'
        and result['reporting_complete'])
    evidence={'result':'PASS' if passed else 'FAILED','seconds':time.monotonic()-began,
        'source_sha256':source,'source_unchanged_during_proof':same_source,
        'scope':'Elapsed original >=60s preparation and 720s window; synthetic credential/directory/feed/quote APIs, original >=60s completed-at feed pacing, owned authenticated native worker, actual 30-post-cutover goal, original raw audit and two fresh replays. Date/time offset is fixed; elapsed durations and slot cadence are not compressed. Not a live provider/production qualification.',
        'network':'denied','actual_vault_access':False,'production_access':False,
        'outer':result,'native_report':report}
    (root/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n')
    from saved_artifact_scan import scan_saved_artifacts
    scan_saved_artifacts(root,(SECRET.encode(),))
    print(json.dumps({'result':evidence['result'],'seconds':evidence['seconds'],'outer':result,
        'goals':report['goals'],'raw_native_audit_passed':report['raw_native_audit_passed'],
        'missing_slot_ids':report['missing_slot_ids'],'saved':str(root/'evidence.json')},indent=2),flush=True)
    return 0 if passed else 1

if __name__=='__main__':raise SystemExit(main())
