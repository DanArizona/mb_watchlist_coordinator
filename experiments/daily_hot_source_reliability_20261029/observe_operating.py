"""One unchanged paced proof; capture both outer-owner and monitor failures."""
import builtins
import importlib.util
import json
import os
from pathlib import Path

ROOT=Path(__file__).resolve().parent


def setup_observed(case,original):
    original(case)
    # The existing monitor observer also remains installed in its owned child.
    case.controller_entry=(*case.controller_entry[:3],str(ROOT/'monitor_observer_child.py'),*case.controller_entry[3:])


def install_owner(owner_type):
    path=ROOT/'operating_exception_observer.py'
    spec=importlib.util.spec_from_file_location('_operating_error_recorder',path)
    recorder=importlib.util.module_from_spec(spec);spec.loader.exec_module(recorder)
    return recorder.install(owner_type)


def finish_report(report_path):
    report=json.loads(report_path.read_text())
    path=report_path.parent/'paced/closed-state/daily_outer_test/operating-owner-error.json'
    read_error=None
    try:error=json.loads(path.read_text()) if path.exists() else None
    except (OSError,ValueError) as failure:error=None;read_error=type(failure).__name__
    report.update(contract='daily-hot-operating-exception-observation-v1',
        underlying_observation_contract='daily-hot-monitor-exception-observation-v1',
        operating_exception_observer=True,operating_exception=error,
        operating_receipt_read_error=read_error,
        diagnostic_result='CAPTURED' if error or report.get('monitor_exception') else
            'RECEIPT_UNREADABLE' if read_error or report.get('monitor_receipt_read_error') else 'NO_EXCEPTION_CAPTURED',
        windows_operating_observation_complete=bool(os.name=='nt' and
            (error or report.get('monitor_exception') or report['result']=='PASS')),
        runtime_change_scope='diagnostic observation in original outer exception handler and monitor wrapper only',
        owner_original_handler_and_cleanup_unchanged=True,
        active_owner_checks_added=False,failed_operation_retried=False,
        watchdog_deadlines_changed=False,original_windows_command69_result='FAILED',root_cause_fixed=False)
    report_path.write_text(json.dumps(report,indent=2)+'\n')
    return report


def main():
    spec=importlib.util.spec_from_file_location('_verified_monitor_observation',ROOT/'observe_monitor.py')
    monitor=importlib.util.module_from_spec(spec);spec.loader.exec_module(monitor)
    installed=[]
    def setup(case,original):
        setup_observed(case,original)
        from mb_watchlist_coordinator.daily_operating import DailyOperatingOwner
        installed.append((DailyOperatingOwner,install_owner(DailyOperatingOwner)))
    monitor.setup_observed=setup
    def progress(*values,**kwargs):
        if len(values)==1 and isinstance(values[0],str) and values[0].startswith('{'):return
        if values and values[0]=='Saved report:':return
        builtins.print(*values,**kwargs)
    monitor.print=progress
    print('OFFLINE outer-owner and controller-monitor exception capture.',flush=True)
    print('Owner recording runs only after an exception. Original stop/cleanup, 60-second feed pacing and all deadlines remain.',flush=True)
    try:code=monitor.main()
    finally:
        for owner,original in reversed(installed):owner._run=original
    report_path=Path(os.environ['MB_DAILY_PACED_SOURCE_PROOF_DIR']).parent/'verification.json'
    report=finish_report(report_path)
    print(json.dumps(report,indent=2),flush=True);print('Saved report:',report_path,flush=True)
    return code


if __name__=='__main__':
    try:raise SystemExit(main())
    except (OSError,ValueError,KeyError,TypeError) as error:
        print('Operating observation refused:',type(error).__name__,str(error),flush=True)
        raise SystemExit(70)
