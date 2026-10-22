"""Compare fresh processes against one unchanged native-generated fixture."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = '3588cf8090279bd014417e9560d10e37c75a6dac'


def inventory(root):
    paths = list((root/'src').rglob('*.py'))
    paths += list((root/'experiments/sampling_promotion_20261016/market_data/src').rglob('*.py'))
    paths += [root/'experiments/coordinator_growth_20261022/qualify.py']
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(paths)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--reference-root', type=Path, required=True)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--reference-repeats', type=int, default=3)
    parser.add_argument('--repeats', type=int, default=100)
    args = parser.parse_args()
    if min(args.repeats, args.reference_repeats) < 1 or args.output.exists():
        parser.error('Positive repeat counts and a new output file are required')
    report = {'contract': 'coordinator-history-cost-comparison-v1', 'status': 'RUNNING',
        'reference_commit': REFERENCE, 'reference_inventory': inventory(args.reference_root),
        'candidate_inventory': inventory(ROOT), 'fixture': str(args.fixture.resolve()),
        'platform': platform.platform(), 'python': sys.version,
        'started_at_utc': datetime.now(timezone.utc).isoformat(),
        'scope': 'Same saved native 1000-receipt/200-publication fixture, elapsed read-only idle/cold checks; no new construction, provider or full capacity qualification',
        'reference_sample_is_diagnostic': True, 'production_access': False,
        'network': 'denied', 'qualification': 'INCOMPLETE'}
    def save():
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    def worker(root, kind, repeats):
        print('Measuring '+('reference' if root == args.reference_root else 'candidate')+' '+kind, flush=True)
        command = [sys.executable, '-I', '-B', str(root/'experiments/coordinator_growth_20261022/qualify.py'),
            '--worker', kind, '--fixture', str(args.fixture.resolve()), '--repeats', str(repeats)]
        child = subprocess.run(command, capture_output=True, text=True, timeout=600)
        if child.returncode:
            raise RuntimeError(child.stderr[-5000:])
        return json.loads(child.stdout)
    save()
    try:
        report['reference'] = worker(args.reference_root, 'measure', args.reference_repeats); save()
        report['candidate'] = worker(ROOT, 'measure', args.repeats); save()
        report['candidate_cold_reopens'] = [worker(ROOT, 'cold', 1) for _ in range(3)]
        if inventory(ROOT) != report['candidate_inventory'] or inventory(args.reference_root) != report['reference_inventory']:
            raise ValueError('Source changed during measurement')
        report.update(status='MEASURED', correctness='PASS',
            performance='PASS' if report['candidate']['gate']=='PASS' and
                all(r['gate']=='PASS' for r in report['candidate_cold_reopens']) else 'FAILED')
    except BaseException as exc:
        report.update(status='FAILED', error_type=type(exc).__name__, error=str(exc))
        save(); raise
    save()
    print(json.dumps({k:v for k,v in report.items() if 'inventory' not in k}, indent=2))
    return 0 if report['performance']=='PASS' else 2


if __name__ == '__main__':
    raise SystemExit(main())
