"""Package the monitor exception observer without copying or editing runtime."""
import argparse,hashlib,json,subprocess,zipfile
from pathlib import Path


def git(repo,*args):return subprocess.check_output(['git','-C',str(repo),*args]).decode().strip()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--destination',type=Path,required=True)
    args=parser.parse_args();repo=Path(__file__).resolve().parents[2]
    if git(repo,'status','--porcelain','--untracked-files=no'):raise ValueError('Committed clean observer required')
    if git(repo,'diff','--name-only','2f56703904db10cf6c47e410f350f60cfa03656f','HEAD','--','src'):
        raise ValueError('Original runtime source changed')
    commit=git(repo,'rev-parse','HEAD');tree=git(repo,'rev-parse','HEAD^{tree}')
    name='hot_monitor_observer_20261029_'+commit[:7]
    args.destination.mkdir(parents=True,exist_ok=True);stage=args.destination/name;stage.mkdir(exist_ok=False)
    prefix='experiments/daily_hot_source_reliability_20261029/'
    pairs=[('observe_monitor.py','observe_monitor.py'),('monitor_observer_child.py','monitor_observer_child.py'),
        ('trace_control.py','trace_control.py'),('69_observe_monitor_exception.cmd','69_observe_monitor_exception.cmd'),
        ('MONITOR_OBSERVATION_README.md','README.md'),
        ('validation/monitor_observer_local_qualification.json','LOCAL_QUALIFICATION.json')]
    for original,target in pairs:
        raw=subprocess.check_output(['git','-C',str(repo),'show','HEAD:'+prefix+original])
        if target.endswith('.cmd'):raw=raw.replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')
        (stage/target).write_bytes(raw)
    files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(stage.iterdir())}
    manifest={'contract':'daily-hot-monitor-observer-source-v1','observer_commit':commit,'observer_tree':tree,
        'uses_original_packet':'daily_hot_source_reliability_20261029_2f56703_5552c5d',
        'source_inventory_sha256':'66fc48d4c4376a1ea0892835a21b393180acb2adb5120306b4bb5929b5979d62',
        'original_runtime_source_files_unchanged':True,'diagnostic_runtime_wrapper':True,'files':files}
    (stage/'OBSERVER_INVENTORY.json').write_text(json.dumps(manifest,indent=2)+'\n')
    archive=args.destination/(name+'.zip')
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED) as z:
        for p in sorted(stage.iterdir()):z.write(p,name+'/'+p.name)
    print(json.dumps({'artifact':str(archive),'stage':str(stage),'observer_commit':commit,
        'observer_tree':tree,'bytes':archive.stat().st_size,
        'sha256':hashlib.sha256(archive.read_bytes()).hexdigest()},indent=2))


if __name__=='__main__':main()
