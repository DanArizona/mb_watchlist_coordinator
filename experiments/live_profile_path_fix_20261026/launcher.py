"""Pinned offline gate and separately human-invoked Windows live profiles."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys


def check_inventory(root):
    """Use stdlib only until delivered source bytes have been checked."""
    path=root/'SOURCE_INVENTORY.json'
    if path.is_symlink():raise ValueError('Inventory differs')
    raw=path.read_bytes();expected=json.loads(raw)['files']
    actual={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()
        and p.relative_to(root).parts[0]!='runs' and p!=path}
    if set(expected)!=actual:raise ValueError('Source set differs')
    for name,sha in expected.items():
        p=root/name
        if p.is_symlink() or not p.resolve().is_relative_to(root) or hashlib.sha256(p.read_bytes()).hexdigest()!=sha:
            raise ValueError('Source bytes differ')
    return hashlib.sha256(raw).hexdigest()


def offline(root,inventory_sha):
    from mb_watchlist_coordinator.recovery_workers import atomic_json
    marker=root/'runs/OFFLINE_ACCEPTED.json'
    if marker.exists():
        if marker.is_symlink() or not marker.is_file():raise ValueError('Acceptance marker differs')
        marker.unlink()  # A failed/interrupted rerun cannot reuse an older PASS.
    before=set((root/'runs/verification').glob('*/verification.json'))
    entry=root/'coordinator/experiments/live_profile_path_fix_20261026/verify.py'
    child=subprocess.Popen([sys.executable,'-I','-B',str(entry),'--output-root',str(root/'runs/verification')],stdout=subprocess.DEVNULL)
    try:code=child.wait(timeout=300)
    except (KeyboardInterrupt,subprocess.TimeoutExpired):
        child.terminate()
        try:child.wait(timeout=2)
        except subprocess.TimeoutExpired:child.kill();child.wait(timeout=2)
        print('Offline entry verification interrupted; no acceptance marker written.',flush=True);return 124
    fresh=set((root/'runs/verification').glob('*/verification.json'))-before
    if len(fresh)!=1:raise ValueError('Fresh verification report absent')
    path=fresh.pop();value=json.loads(path.read_text())
    if (value['result'] not in ('PASS','FAILED') or (code==0)!=(value['result']=='PASS')
            or code==0 and (value['failures'] or value['errors'] or value['tests']<1)):
        raise ValueError('Verification report and exit differ')
    print(json.dumps(value,indent=2),flush=True);print('Saved report:',path,flush=True)
    if code==0:
        atomic_json(marker,{'inventory_sha256':inventory_sha,
            'report':str(path),'report_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'executable':str(Path(sys.executable).resolve()),'python':list(sys.version_info[:3]),
            'platform':platform.platform()})
    return code


def require_offline(root,inventory_sha):
    from mb_watchlist_coordinator.live_profile import bounded_json
    if sys.platform!='win32':raise ValueError('Installed live profiles require the qualified Windows host')
    marker=bounded_json(root/'runs/OFFLINE_ACCEPTED.json')
    path=Path(marker['report'])
    if (not path.resolve().is_relative_to(root/'runs/verification')
            or marker['inventory_sha256']!=inventory_sha
            or marker['executable']!=str(Path(sys.executable).resolve())
            or marker['python']!=list(sys.version_info[:3]) or marker['platform']!=platform.platform()
            or marker['report_sha256']!=hashlib.sha256(path.read_bytes()).hexdigest()):
        raise ValueError('Run command54 in this exact host/environment first')
    value=bounded_json(path)
    if value['result']!='PASS' or value['failures'] or value['errors']:
        raise ValueError('Offline qualification has not passed')


def main(root,argv=None):
    root=Path(root).resolve()
    try:sha=check_inventory(root)
    except Exception:
        print('Profile entry BLOCKED: source inventory differs.',flush=True);return 70
    sys.path[:0]=[str(root/'coordinator/src'),str(root/'coordinator/experiments/sampling_promotion_20261016/market_data/src')]
    from mb_watchlist_coordinator.live_profile import run_live,stop_live
    parser=argparse.ArgumentParser()
    sub=parser.add_subparsers(dest='mode',required=True)
    sub.add_parser('verify');sub.add_parser('stop')
    for name in ('ordinary','recovery'):
        p=sub.add_parser(name);p.add_argument('opening');p.add_argument('focus');p.add_argument('ecfg')
        p.add_argument('--market-open-confirmed',action='store_true')
    args=parser.parse_args(argv)
    try:
        if args.mode=='verify':
            print('OFFLINE credential-bound live entry qualification. Synthetic credentials/SDK/feed only; no API or password.',flush=True)
            return offline(root,sha)
        if args.mode=='stop':print(stop_live(root),flush=True);return 0
        require_offline(root,sha)
        print('ISOLATED LIVE HOT: 12-minute frozen window after >=60s preparation lead; one admitted symbol.',flush=True)
        print('Maximum 60 Hot + 3 identity quote permits; 2 directory permits; 10 feed attempts paced >=60s after completion.',flush=True)
        print('Separate profile invocation. Original 3s worker progress, 8s credentials, 10s cleanup/60s reporting; one hidden prompt.',flush=True)
        print('Only experimental Hot collects. Normal SDK refresh can update the shared token database.',flush=True)
        folder,result=run_live(root,args.opening,args.focus,args.ecfg,
            'ordinary' if args.mode=='ordinary' else 'owned_worker_recovery',market_open_confirmed=args.market_open_confirmed)
        print(json.dumps(result,indent=2),flush=True);print('Saved summary:',folder/'summary.json',flush=True)
        return 0 if result['outer']['result'] in ('PASS','PASS_WITH_WARNINGS','READINESS_ONLY') else 1
    except KeyboardInterrupt:
        print('Operator interrupted before a completed profile result.',flush=True);return 130
    except Exception:
        print('Profile entry BLOCKED: validation/dependency/offline gate or owned startup failed. No automatic retry.',flush=True);return 70


if __name__=='__main__':raise SystemExit(main(Path(__file__).resolve().parent))
