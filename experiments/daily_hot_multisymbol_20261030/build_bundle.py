"""Source-pinned multi-symbol candidate and offline qualification; no installer."""
import argparse
import hashlib
import json
import re
from pathlib import Path
import subprocess
import sys
import zipfile

BASE = '8fcdaddff54c92f4e9f33416ef15e79b899dcbc5'
NATIVE = 'd37d2c37e3ac9cc2c860d0a2313a1526e30fd23e'
EXPERIMENT = 'experiments/daily_hot_multisymbol_20261030'


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args]).decode().strip()


def copy(root, name, destination):
    data = subprocess.check_output(['git', '-C', str(root), 'show', 'HEAD:'+name])
    if name.endswith('.cmd'): data = data.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--market-data-root', required=True, type=Path)
    parser.add_argument('--destination', required=True, type=Path)
    parser.add_argument('--coordinator-public-commit',required=True)
    args = parser.parse_args()
    if re.fullmatch('[0-9a-f]{40}',args.coordinator_public_commit)is None:raise ValueError('Exact published coordinator commit required')
    repo = Path(__file__).resolve().parents[2]
    native = args.market_data_root.resolve()
    for root in (repo, native):
        if git(root, 'status', '--porcelain', '--untracked-files=no'):
            raise ValueError('Committed clean source required')
    if git(native, 'rev-parse', 'HEAD') != NATIVE:
        raise ValueError('Accepted native source required')
    changed = git(repo, 'diff', '--name-only', BASE, 'HEAD', '--', 'src').splitlines()
    expected = ['src/mb_watchlist_coordinator/'+name+'.py' for name in ('daily_authenticated_worker','daily_collector','daily_controller','daily_epoch_collector','daily_epoch_integrity',
        'daily_launch','daily_multi_identity','daily_multi_publication','daily_operating','daily_operating_review',
        'daily_operator','daily_session','daily_source','daily_supervision','daily_worker_view','operating_plan')]
    if sorted(changed) != sorted(expected): raise ValueError('Unexpected runtime change scope')
    sys.path[:0] = [str(repo/'src'), str(native/'src')]
    from mb_watchlist_coordinator.daily_operator import CONTRACT, DEPENDENCIES, MARKET_BASE, WATCHLIST_BASE, MAX_OPENING_UNI
    from mb_watchlist_coordinator.operating_plan import proposed_policy,MULTI_PROFILE
    from mb_watchlist_coordinator.sampling_requests import digest
    args.destination.mkdir(parents=True, exist_ok=True)
    stage = args.destination/'p85'
    stage.mkdir(exist_ok=False)
    for root, prefix, sections in ((repo, 'coordinator', ('src', 'tests')), (native, 'market_data', ('src',))):
        for section in sections:
            for name in git(root, 'ls-files', section).splitlines():
                if '__pycache__' in Path(name).parts or name.endswith(('.pyc', '.pyo')):
                    raise ValueError('Bytecode refused')
                copy(root, name, stage/prefix/name)
    for name in ('run.py', 'README.md', 'RELEASE_REVIEW.md', '85_verify_multisymbol.cmd',
                 '86_review_multisymbol.cmd', 'hot_daily.cmd'):
        copy(repo, EXPERIMENT+'/'+name, stage/name)
    for name in ('history_probe.py','timing_probe.py'):
        copy(repo,EXPERIMENT+'/'+name,stage/'coordinator'/EXPERIMENT/name)
    copy(repo,'experiments/daily_hot_operating_20261028/capacity_probe.py',
        stage/'coordinator/experiments/daily_hot_operating_20261028/capacity_probe.py')
    evidence = {
        'WINDOWS_OPERATOR_PREDECESSOR.json':'hot_operating_release_20261030/WINDOWS_ACCEPTANCE.json',
        'WINDOWS_DEPLOYMENT_PREDECESSOR.json':'hot_operating_release_20261030/WINDOWS_DEPLOYMENT_ACCEPTANCE.json',
        'LIVE_DAILY_PATH.json': 'market_open_daily_check_20261029/WINDOWS_LIVE_ACCEPTANCE.json',
        'WINDOWS_MEMBERSHIP.json': 'membership_status_20261030/WINDOWS_ACCEPTANCE.json',
        'WINDOWS_LAUNCH.json': 'daily_hot_launch_20261029/WINDOWS_ACCEPTANCE.json',
        'WINDOWS_READ_SHARING.json': 'daily_hot_windows_evidence_read_20261029/WINDOWS_ACCEPTANCE.json',
        'AFTER_HOURS_PROVIDER.json': 'after_hours_provider_20261029/WINDOWS_LIVE_ACCEPTANCE.json',
        'CAPACITY_COMPONENT_ORIGINAL_FAILED_PACKET.json': 'daily_hot_operating_20261028/validation/windows_3c0f8cd_review.json'}
    for name, original in evidence.items(): copy(repo, 'experiments/'+original, stage/'evidence'/name)
    release = {'contract': CONTRACT, 'status': 'CANDIDATE_NOT_ACTIVATED',
        'proposed_first_session': '2026-11-02', 'deployment': 'Side-by-side extracted release; existing production repositories stay installed',
        'production_baselines': {'market_data': MARKET_BASE, 'watchlists': WATCHLIST_BASE},
        'dependency_versions': DEPENDENCIES, 'policy_profile':MULTI_PROFILE,'policy_sha256': digest(proposed_policy(MULTI_PROFILE)), 'policy': proposed_policy(MULTI_PROFILE),
        'initial_capacity': {'opening_uni_maximum': MAX_OPENING_UNI, 'uni_with_40_additions_maximum': MAX_OPENING_UNI+40,
            'opening_focus_maximum': 40, 'focus_with_40_additions_maximum': 80, 'hot_maximum': 40},
        'fresh_start': 'Pre-open; password must be accepted before 09:29:00 ET. No fresh after-open start or backfill in this increment.',
        'manual_resume': 'Original configuration/state/catalog and budgets, new owned outer after observed cleanup; original 15-second hold',
        'rollback': 'Stop and verify only the Hot owned scope, preserve membership and journals, continue installed Uni/Focus/Health',
        'evidence': evidence, 'evidence_scope': 'Accepted component/bounded-live scopes only; original failed packet verdict preserved',
        'full_day_capacity_qualified': False, 'production_activation_approved': False}
    (stage/'RELEASE.json').write_text(json.dumps(release, indent=2)+'\n')
    source = {'coordinator_commit': git(repo, 'rev-parse', 'HEAD'), 'market_data_commit': NATIVE,
              'accepted_operating_predecessor': BASE, 'production_native_baseline': MARKET_BASE,
              'coordinator_public_commit':args.coordinator_public_commit,
              'market_data_public_commit':'37c22983bc92055dd322085f191b054921d896d2',
              'coordinator_tree':git(repo,'rev-parse','HEAD^{tree}'),
              'market_data_tree':git(native,'rev-parse','HEAD^{tree}')}
    filename = 'hot_multisymbol_20261031_'+source['coordinator_commit'][:7]+'.zip'
    for name in ('README.md', 'RELEASE_REVIEW.md'):
        path = stage/name
        path.write_bytes(path.read_bytes().replace(b'@@ZIP@@', filename.encode()))
    files = {p.relative_to(stage).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(stage.rglob('*')) if p.is_file()}
    (stage/'SOURCE_INVENTORY.json').write_text(json.dumps({'contract': 'daily-hot-operating-release-source-v1',
        'source': source, 'runtime_changes': changed, 'files': files}, indent=2, sort_keys=True)+'\n')
    archive = args.destination/filename
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED) as z:
        for path in sorted(stage.rglob('*')):
            if path.is_file(): z.write(path, 'p85/'+path.relative_to(stage).as_posix())
    print(json.dumps({'archive': str(archive), 'stage': str(stage), 'source': source,
        'tree': git(repo, 'rev-parse', 'HEAD^{tree}'), 'bytes': archive.stat().st_size,
        'sha256': hashlib.sha256(archive.read_bytes()).hexdigest()}, indent=2))


if __name__ == '__main__': main()
