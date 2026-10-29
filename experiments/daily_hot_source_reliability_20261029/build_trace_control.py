"""Package only the diagnostic helper; reuse the immutable original packet."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile


def git(root,*args):
    return subprocess.check_output(['git','-C',str(root),*args]).decode().strip()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--destination',type=Path,required=True)
    args=parser.parse_args();repo=Path(__file__).resolve().parents[2]
    if git(repo,'status','--porcelain','--untracked-files=no'):
        raise ValueError('Clean committed helper required')
    if git(repo,'diff','--name-only','2f56703904db10cf6c47e410f350f60cfa03656f','HEAD','--','src'):
        raise ValueError('Runtime changed since the original packet')
    commit=git(repo,'rev-parse','HEAD')
    name='hot_trace_control_20261029_'+commit[:7]
    args.destination.mkdir(parents=True,exist_ok=True)
    stage=args.destination/name;stage.mkdir(exist_ok=False)
    prefix='experiments/daily_hot_source_reliability_20261029/'
    for original,filename in [('trace_control.py','trace_control.py'),
            ('68_control_periodic_stack_dumps.cmd','68_control_periodic_stack_dumps.cmd'),
            ('TRACE_CONTROL_README.md','README.md'),
            ('validation/local_stack_dump_control_verification.json','LOCAL_CONTROL.json')]:
        raw=subprocess.check_output(['git','-C',str(repo),'show','HEAD:'+prefix+original])
        if filename.endswith('.cmd'):raw=raw.replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')
        (stage/filename).write_bytes(raw)
    files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(stage.iterdir())}
    manifest={'contract':'daily-hot-stack-dump-control-source-v1','control_commit':commit,
        'control_tree':git(repo,'rev-parse','HEAD^{tree}'),
        'original_runtime_coordinator_commit':'2f56703904db10cf6c47e410f350f60cfa03656f',
        'original_runtime_native_commit':'5552c5db43351d1a9ae8d376196cc99ba9c7f05d',
        'original_packet':'daily_hot_source_reliability_20261029_2f56703_5552c5d',
        'runtime_changes':False,'files':files}
    (stage/'CONTROL_INVENTORY.json').write_text(json.dumps(manifest,indent=2)+'\n')
    archive=args.destination/(name+'.zip')
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED) as z:
        for p in sorted(stage.iterdir()):z.write(p,name+'/'+p.name)
    print(json.dumps({'artifact':str(archive),'stage':str(stage),'control_commit':commit,
        'control_tree':manifest['control_tree'],'bytes':archive.stat().st_size,
        'sha256':hashlib.sha256(archive.read_bytes()).hexdigest()},indent=2))


if __name__=='__main__':main()
