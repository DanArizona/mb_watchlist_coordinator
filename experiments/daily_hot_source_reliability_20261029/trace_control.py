"""One controlled offline run: original paced proof, periodic stack dumps off.

The frozen packet is verified before import and after execution. Exactly two
test-only trace_stacks flags are changed in memory. No source file is edited.
"""
import argparse
import ast
from datetime import datetime,timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import sys
import time
import types
import unittest
from uuid import uuid4

INVENTORY_SHA='66fc48d4c4376a1ea0892835a21b393180acb2adb5120306b4bb5929b5979d62'
COORDINATOR='2f56703904db10cf6c47e410f350f60cfa03656f'
NATIVE='5552c5db43351d1a9ae8d376196cc99ba9c7f05d'
PACKET='daily_hot_source_reliability_20261029_2f56703_5552c5d'
METHOD='test_three_real_paced_feed_children_reconcile_while_owned_hot_collection_continues'


def verified_inventory(root):
    path=root/'SOURCE_INVENTORY.json'
    if hashlib.sha256(path.read_bytes()).hexdigest()!=INVENTORY_SHA:
        raise ValueError('Original command-67 inventory required')
    m=json.loads(path.read_text())
    if (m['source']['coordinator_commit']!=COORDINATOR
            or m['source']['market_data_commit']!=NATIVE):
        raise ValueError('Frozen source differs')
    names={p.relative_to(root).as_posix() for p in root.rglob('*')
        if p.is_file() and p.relative_to(root).parts[0]!='runs' and p!=path}
    if names!=set(m['files']):raise ValueError('Frozen source file set differs')
    for name,sha in m['files'].items():
        p=root/name
        if p.is_symlink() or not p.resolve().is_relative_to(root):
            raise ValueError('Frozen source path differs')
        if hashlib.sha256(p.read_bytes()).hexdigest()!=sha:
            raise ValueError('Frozen source bytes differ')
    return m


class DisablePeriodicDumps(ast.NodeTransformer):
    def __init__(self):self.changed=[]
    def visit_Assign(self,node):
        if len(node.targets)==1:
            target=node.targets[0]
            if (isinstance(target,ast.Subscript) and isinstance(target.value,ast.Name)
                    and target.value.id in ('scene','auth_scene')
                    and isinstance(target.slice,ast.Constant) and target.slice.value=='trace_stacks'
                    and isinstance(node.value,ast.Constant) and node.value.value is True):
                self.changed.append({'scenario':target.value.id,'line':node.lineno})
                node.value=ast.copy_location(ast.Constant(False),node.value)
        return node


class Log:
    def __init__(self,file):self.file=file
    def write(self,value):self.file.write(value);sys.stdout.write(value)
    def flush(self):self.file.flush();sys.stdout.flush()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--packet-root',type=Path,
        default=Path(__file__).resolve().parent.parent/PACKET)
    parser.add_argument('--output-root',type=Path,default=Path(__file__).resolve().parent/'runs')
    args=parser.parse_args()
    root=args.packet_root.resolve();manifest=verified_inventory(root)
    sys.dont_write_bytecode=True;os.environ['PYTHONDONTWRITEBYTECODE']='1'
    sys.path[:0]=[str(root/'coordinator/src'),str(root/'market_data/src'),str(root/'coordinator/tests')]
    def denied(*a,**k):raise OSError('Network denied during the offline diagnostic control')
    socket.socket.connect=socket.socket.connect_ex=socket.create_connection=socket.getaddrinfo=denied
    path=root/'coordinator/tests/test_daily_source_reliability.py'
    raw=path.read_bytes();tree=ast.parse(raw,filename=str(path))
    transform=DisablePeriodicDumps();tree=transform.visit(tree);ast.fix_missing_locations(tree)
    if sorted(x['scenario'] for x in transform.changed)!=['auth_scene','scene']:
        raise ValueError('Expected exactly the two known test-only periodic-stack flags')
    module=types.ModuleType('_hot_trace_control_fixture');module.__file__=str(path)
    sys.modules[module.__name__]=module
    exec(compile(tree,str(path),'exec'),module.__dict__)
    suite=unittest.TestSuite([module.DailyPacedSourceOwnerTests(METHOD)])
    run=args.output_root.resolve()/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ_')+uuid4().hex[:8])
    run.mkdir(parents=True,exist_ok=False)
    os.environ['MB_DAILY_PACED_SOURCE_PROOF_DIR']=str(run/'paced')
    print('OFFLINE diagnostic control: ONE original paced proof; periodic diagnostic stack dumping OFF.',flush=True)
    print('Original frozen runtime, assertions, 60-second pacing and watchdog gates. No password, API or production changes.',flush=True)
    print('Allow about 2.5 minutes. The original Windows 49/50 FAILED result is preserved.',flush=True)
    began=time.monotonic()
    with (run/'tests.log').open('w',encoding='utf-8') as f:
        result=unittest.TextTestRunner(stream=Log(f),verbosity=2).run(suite)
    verified_inventory(root)
    path=run/'paced/proof.json';proof=json.loads(path.read_text()) if path.exists() else None
    stacks=list((run/'paced/closed-state').rglob('*-thread-stacks.log'))
    passed=bool(result.wasSuccessful() and result.testsRun==1 and not result.skipped
        and proof and proof['result']=='PASS' and not stacks)
    report={'contract':'daily-hot-periodic-stack-dump-control-v1',
        'result':'PASS' if passed else 'FAILED','tests':result.testsRun,
        'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),
        'seconds':time.monotonic()-began,'platform':sys.platform,'python':list(sys.version_info[:3]),
        'windows_control_passed':bool(passed and os.name=='nt'),
        'source':manifest['source'],'source_inventory_sha256':INVENTORY_SHA,
        'original_test_source_sha256':hashlib.sha256(raw).hexdigest(),
        'changed_test_only_flags':transform.changed,'periodic_stack_dumps':False,
        'unexpected_stack_files':[str(p) for p in stacks],
        'original_source_files_unchanged':True,'runtime_changes':False,
        'original_windows_command67_result':'FAILED','original_windows_command67_passed':49,
        'original_windows_command67_tests':50,'root_cause_proven':False,
        'control_scope':'test instrumentation isolation; one pass alone does not prove the precise native crash cause',
        'network':'denied','actual_vault_access':False,'actual_broker_sdk_used':False,
        'production_changes':False,'production_hot_enabled':False,'live_launch_available':False,
        'operating_release_qualified':False,'provider_capacity_qualified':False,'full_day_capacity_qualified':False,
        'paced_proof':proof}
    (run/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2),flush=True);print('Saved report:',run/'verification.json',flush=True)
    return 0 if passed else 1


if __name__=='__main__':
    try:raise SystemExit(main())
    except (OSError,ValueError,KeyError,TypeError) as error:
        print('Diagnostic control refused:',type(error).__name__,str(error),flush=True)
        raise SystemExit(70)
