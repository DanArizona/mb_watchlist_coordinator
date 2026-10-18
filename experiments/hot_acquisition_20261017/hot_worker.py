"""Private worker; accepts only fresh directories inside this review's runs."""
from __future__ import annotations
import os
import sys
import threading
from datetime import datetime,timezone
from pathlib import Path


def main():
    experiment=Path(__file__).resolve().parent;root=experiment.parent.parent
    sys.path[:0]=[str(root/'src'),str(root/'experiments/sampling_promotion_20261016/market_data/src'),str(experiment)]
    from run_hot_proof import verify_sources
    verify_sources(root,experiment)
    if len(sys.argv)!=4 or sys.argv[2] not in ('coordinator','uni','focus','hot') or sys.argv[3] not in ('run','after_dispatch','after_response','after_assembled','after_journal_commit'):
        raise ValueError('Private Hot worker arguments differ')
    folder=Path(sys.argv[1]).resolve()
    if not folder.is_relative_to((experiment/'runs').resolve()) or not folder.is_dir():raise ValueError('Worker path must stay within this experiment runs')
    import test_hot_acquisition  # installs only the reviewed market-data extension path
    from hot_proof import append_line,load_context,load_control
    mode,stage=sys.argv[2:];stop=threading.Event();cycles=0
    def stop_watcher():
        while not stop.wait(0.05):
            if (folder/'STOP').exists():stop.set()
    threading.Thread(target=stop_watcher,daemon=True).start()
    def status(value):
        nonlocal cycles
        cycles+=1
        append_line(folder/(mode+'_status.jsonl'),dict(value,pid=os.getpid(),cycles=cycles))
        if (folder/'STOP').exists():stop.set()
    status({'status':'starting'})
    if mode=='coordinator':
        service=load_control(folder)[1]
        result=service.run(stop,on_status=status)
    else:
        store,c,clock,p=load_context(folder,mode)
        if c['logical_now']:
            class LogicalDatetime(datetime):
                @classmethod
                def now(cls,tz=None):return clock().astimezone(tz or timezone.utc)
            import mb_market_data.schwab_quotes
            mb_market_data.schwab_quotes.datetime=LogicalDatetime
        if stage!='run':
            from mb_market_data.sampling_acquisition import ExplicitPollSlot
            def fault(actual):
                if actual==stage:os._exit(73)
            p.sample(ExplicitPollSlot(p.settings.channel,p.settings.window.start_at,p.settings.seconds),fault_hook=fault)
            raise RuntimeError('Fault injection was not reached')
        result=p.run_loop(stop,on_status=status)
    status(result)
    return 0


if __name__=='__main__':raise SystemExit(main())
