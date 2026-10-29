"""Observe one Python monitor exception, then preserve its original propagation."""
import json
from pathlib import Path
import runpy
import sys

RECEIPT='controller-monitor-error.json'


def capture(controller,error):
    """First failure only; no exception body, locals, provider data or new DB reads."""
    frames=[];tb=error.__traceback__
    while tb is not None:
        frame=tb.tb_frame;module=frame.f_globals.get('__name__','')
        if module.startswith(('mb_watchlist_coordinator.','mb_market_data.')):
            frames.append({'module':module,'function':frame.f_code.co_name,'line':tb.tb_lineno})
        tb=tb.tb_next
    value={'contract':'daily-hot-monitor-exception-v1',
        'observed_at_utc':controller.clock().isoformat(),
        'error_type':type(error).__name__,'error_module':type(error).__module__,
        'errno':getattr(error,'errno',None),'winerror':getattr(error,'winerror',None),
        'sqlite_errorcode':getattr(error,'sqlite_errorcode',None),
        'sqlite_errorname':getattr(error,'sqlite_errorname',None),
        'filename':str(error.filename) if isinstance(error,OSError) and error.filename is not None else None,
        'frames':frames[-16:],'invocation':controller.invocation,
        'driver_live_age_monotonic_seconds':controller.monotonic()-controller.last_live,
        'previous_worker_report':dict(controller.worker_report),
        'previous_heartbeat_check':getattr(controller.worker,'last_heartbeat_check',None),
        'failure_observed_before_original_handler':True,'monitor_operation_retried':False}
    causes=[];cause=error.__cause__;seen={id(error)}
    while cause is not None and id(cause) not in seen and len(causes)<4:
        seen.add(id(cause))
        causes.append({'error_type':type(cause).__name__,
            'errno':getattr(cause,'errno',None),'winerror':getattr(cause,'winerror',None),
            'filename':str(cause.filename) if isinstance(cause,OSError) and cause.filename is not None else None})
        cause=cause.__cause__
    value['causes']=causes
    try:
        # The original exception has already occurred. A failed diagnostic write
        # must never replace it or enter the monitor operation a second time.
        with (Path(controller.root)/RECEIPT).open('x',encoding='utf-8') as out:
            json.dump(value,out,indent=2);out.write('\n')
    except Exception:
        pass


def install(controller_type):
    original=controller_type._monitor_once
    def observed(controller):
        try:return original(controller)
        except BaseException as error:
            try:capture(controller,error)
            except Exception:pass
            raise
    controller_type._monitor_once=observed
    return original


def main():
    fixture,scene,*rest=sys.argv[1:]
    fixture=Path(fixture).resolve()
    config=json.loads(Path(scene).read_text())
    sys.path[:0]=[str(fixture.parents[2]/'src'),config['native_src']]
    from mb_watchlist_coordinator.daily_controller import DailyController
    install(DailyController)
    sys.argv=[str(fixture),scene,*rest]
    runpy.run_path(str(fixture),run_name='__main__')


if __name__=='__main__':main()
