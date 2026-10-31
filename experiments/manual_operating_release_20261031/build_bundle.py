"""Build the side-by-side manual operating candidate from committed source."""
import argparse,hashlib,json,subprocess,sys,zipfile
from pathlib import Path

BASE='44a7e4a4951fbf3c63c741134dcb23fd950642cd'
NATIVE='d37d2c37e3ac9cc2c860d0a2313a1526e30fd23e'
EXPERIMENT='experiments/manual_operating_release_20261031'


def git(root,*args):return subprocess.check_output(['git','-C',str(root),*args]).decode().strip()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--market-data-root',type=Path,required=True)
    parser.add_argument('--destination',type=Path,required=True);args=parser.parse_args()
    repo=Path(__file__).resolve().parents[2];native=args.market_data_root.resolve()
    for root in(repo,native):
        if git(root,'status','--porcelain','--untracked-files=no'):raise ValueError('Committed clean source required')
    if git(native,'rev-parse','HEAD')!=NATIVE:raise ValueError('Pinned accepted native source required')
    changed=git(repo,'diff','--name-only',BASE,'HEAD','--','src').splitlines()
    if changed!=['src/mb_watchlist_coordinator/daily_operator.py']:raise ValueError('Only operator delivery may change')
    sys.path[:0]=[str(repo/'src'),str(native/'src')]
    from mb_watchlist_coordinator.daily_operator import CONTRACT,DEPENDENCIES,MARKET_BASE,WATCHLIST_BASE,MAX_OPENING_UNI,MANUAL_QUALIFICATION
    from mb_watchlist_coordinator.operating_plan import proposed_policy,BROKER_MANUAL_PROFILE
    from mb_watchlist_coordinator.sampling_requests import digest
    args.destination.mkdir(parents=True,exist_ok=True);stage=args.destination/'p94';stage.mkdir(exist_ok=False)
    def copy(root,name,target):
        data=subprocess.check_output(['git','-C',str(root),'show','HEAD:'+name])
        if name.endswith('.cmd'):data=data.replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')
        target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
    for root,prefix,sections in((repo,'coordinator',('src','tests')),(native,'market_data',('src',))):
        for name in git(root,'ls-files',*sections).splitlines():
            if '__pycache__'in Path(name).parts or name.endswith(('.pyc','.pyo')):raise ValueError('Bytecode is not source')
            copy(root,name,stage/prefix/name)
    for name in('run.py','README.md','RELEASE_REVIEW.md','94_verify_manual_operating_release.cmd',
                '95_review_manual_operating_release.cmd','manual_daily.cmd'):
        copy(repo,EXPERIMENT+'/'+name,stage/name)
    name='experiments/daily_hot_operating_20261028/capacity_probe.py';copy(repo,name,stage/'coordinator'/name)
    evidence={
        'WINDOWS_MANUAL_IDENTITY.json':'manual_broker_identity_20261031/WINDOWS_ACCEPTANCE.json',
        'WINDOWS_SHARED_MANUAL.json':'manual_daily_controller_20261031/WINDOWS_ACCEPTANCE.json',
        'WINDOWS_MANUAL_INTERFACE.json':'manual_membership_20261031/WINDOWS_ACCEPTANCE.json',
        'WINDOWS_OPERATOR_PREDECESSOR.json':'hot_operating_release_20261030/WINDOWS_ACCEPTANCE.json',
        'WINDOWS_DEPLOYMENT_PREDECESSOR.json':'hot_operating_release_20261030/WINDOWS_DEPLOYMENT_ACCEPTANCE.json',
        'LIVE_DAILY_PATH.json':'market_open_daily_check_20261029/WINDOWS_LIVE_ACCEPTANCE.json',
        'WINDOWS_MEMBERSHIP.json':'membership_status_20261030/WINDOWS_ACCEPTANCE.json',
        'WINDOWS_LAUNCH.json':'daily_hot_launch_20261029/WINDOWS_ACCEPTANCE.json',
        'WINDOWS_READ_SHARING.json':'daily_hot_windows_evidence_read_20261029/WINDOWS_ACCEPTANCE.json',
        'AFTER_HOURS_PROVIDER.json':'after_hours_provider_20261029/WINDOWS_LIVE_ACCEPTANCE.json',
        'CAPACITY_COMPONENT_ORIGINAL_FAILED_PACKET.json':'daily_hot_operating_20261028/validation/windows_3c0f8cd_review.json'}
    for target,original in evidence.items():copy(repo,'experiments/'+original,stage/'evidence'/target)
    policy=proposed_policy(BROKER_MANUAL_PROFILE)
    release={'contract':CONTRACT,'status':'CANDIDATE_NOT_ACTIVATED','proposed_first_session':'2026-11-03',
        'planning_date_is_activation_approval':False,'approved_monday_p85_changed':False,
        'deployment':'Side-by-side extracted release; existing production repositories stay installed',
        'production_baselines':{'market_data':MARKET_BASE,'watchlists':WATCHLIST_BASE},'dependency_versions':DEPENDENCIES,
        'policy_profile':BROKER_MANUAL_PROFILE,'policy_sha256':digest(policy),'policy':policy,
        'operator_qualification_contract':MANUAL_QUALIFICATION,
        'initial_capacity':{'opening_uni_maximum':MAX_OPENING_UNI,'uni_with_additions_maximum':MAX_OPENING_UNI+40,
            'opening_focus_maximum':40,'focus_with_additions_maximum':80,'hot_maximum':40},
        'manual_controls':'Original live reviewed controller only; fixed actor operator:masterbot; close window does not stop collection',
        'saved_manual_feedback':'Read-only after stop; no edit grant, process start or provider access',
        'fresh_start':'Pre-open; password accepted before 09:29 ET; no fresh after-open start or backfill',
        'manual_resume':'Original complete state/config/catalog/budgets; observed exit; new exact review; original 15-second hold',
        'rollback':'Stop/verify only this owned Hot scope; preserve requests/membership/receipts/journals; keep Uni/Focus/Health running',
        'evidence':evidence,'evidence_scope':'Accepted component/bounded-live scopes retained; new qualification is operator composition only',
        'provider_capacity_qualified':False,'full_day_capacity_qualified':False,'production_activation_approved':False}
    (stage/'RELEASE.json').write_text(json.dumps(release,indent=2)+'\n')
    source={'coordinator_commit':git(repo,'rev-parse','HEAD'),'coordinator_tree':git(repo,'rev-parse','HEAD^{tree}'),
        'accepted_manual_predecessor':BASE,'market_data_commit':NATIVE,'production_native_baseline':MARKET_BASE}
    filename='manual_operating_release_20261031_'+source['coordinator_commit'][:7]+'.zip'
    for name in('README.md','RELEASE_REVIEW.md'):
        path=stage/name;path.write_bytes(path.read_bytes().replace(b'@@ZIP@@',filename.encode()))
    manifest={'contract':'daily-hot-operating-release-source-v1','source':source,'runtime_changes':changed,
        'controller_identity_collector_gui_changed':False,
        'files':{p.relative_to(stage).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in sorted(stage.rglob('*'))if p.is_file()}}
    (stage/'SOURCE_INVENTORY.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
    archive=args.destination/filename
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED)as z:
        for path in sorted(stage.rglob('*')):
            if path.is_file():z.write(path,'p94/'+path.relative_to(stage).as_posix())
    print(json.dumps({'archive':str(archive),'bytes':archive.stat().st_size,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),
        'stage':str(stage),'source':source},indent=2))


if __name__=='__main__':main()
