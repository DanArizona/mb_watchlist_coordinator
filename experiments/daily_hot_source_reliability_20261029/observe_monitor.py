"""Run the verified dump-off control with a controller-only exception observer."""
import argparse
import builtins
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parent
CONTROL_SHA='8f51e7886fd7f73f4853d959082c0af469eacbc6c1bef48432baa63809756b81'


def setup_observed(self,original):
    original(self)
    command=self.controller_entry
    self.controller_entry=(*command[:3],str(ROOT/'monitor_observer_child.py'),*command[3:])


def main():
    path=ROOT/'trace_control.py'
    if hashlib.sha256(path.read_bytes()).hexdigest()!=CONTROL_SHA:
        raise ValueError('Unchanged original diagnostic-control helper required')
    spec=importlib.util.spec_from_file_location('_verified_dump_control',path)
    control=importlib.util.module_from_spec(spec);spec.loader.exec_module(control)
    parser=argparse.ArgumentParser()
    parser.add_argument('--packet-root',type=Path,default=ROOT.parent/control.PACKET)
    parser.add_argument('--output-root',type=Path,default=ROOT/'runs')
    args=parser.parse_args();root=args.packet_root.resolve();control.verified_inventory(root)
    sys.dont_write_bytecode=True;os.environ['PYTHONDONTWRITEBYTECODE']='1'
    sys.path[:0]=[str(root/'coordinator/src'),str(root/'market_data/src'),str(root/'coordinator/tests')]
    import test_daily_operating as fixtures
    original=fixtures.DailyOperatingTests.setUp
    fixtures.DailyOperatingTests.setUp=lambda case:setup_observed(case,original)
    def progress(*values,**kwargs):
        if len(values)==1 and isinstance(values[0],str) and values[0].startswith('{'):return
        if values and values[0]=='Saved report:':return
        builtins.print(*values,**kwargs)
    control.print=progress
    print('OFFLINE first-monitor-exception observation. No periodic native stack dumping.',flush=True)
    print('The observer saves error type, code and trusted frames, then re-raises the same error.',flush=True)
    sys.argv=[str(path),'--packet-root',str(root),'--output-root',str(args.output_root)]
    try:code=control.main()
    finally:fixtures.DailyOperatingTests.setUp=original
    paced=Path(os.environ['MB_DAILY_PACED_SOURCE_PROOF_DIR']);run=paced.parent
    report_path=run/'verification.json';report=json.loads(report_path.read_text())
    receipt=paced/'closed-state/daily_hot_test/controller-monitor-error.json'
    read_error=None
    try:error=json.loads(receipt.read_text()) if receipt.exists() else None
    except (OSError,ValueError) as failure:error=None;read_error=type(failure).__name__
    report.update(contract='daily-hot-monitor-exception-observation-v1',
        underlying_control_contract='daily-hot-periodic-stack-dump-control-v1',
        controller_exception_observer=True,monitor_exception=error,
        diagnostic_result='CAPTURED' if error else 'RECEIPT_UNREADABLE' if read_error else 'NO_MONITOR_EXCEPTION_CAPTURED',
        monitor_receipt_read_error=read_error,
        original_runtime_source_files_unchanged=True,
        runtime_changes=True,
        runtime_change_scope='diagnostic exception wrapper only; original runtime source bytes and original handler unchanged',
        diagnostic_wrapper_rethrows_original_exception=True,
        windows_monitor_observation_complete=bool(os.name=='nt' and (error or code==0)),
        root_cause_fixed=False)
    report_path.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2),flush=True);print('Saved report:',report_path,flush=True)
    return code


if __name__=='__main__':
    try:raise SystemExit(main())
    except (OSError,ValueError,KeyError,TypeError) as error:
        print('Monitor observation refused:',type(error).__name__,str(error),flush=True)
        raise SystemExit(70)
