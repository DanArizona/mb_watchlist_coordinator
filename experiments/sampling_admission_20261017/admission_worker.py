"""Private bounded worker; synthetic quote source and experiment-local paths."""
from __future__ import annotations
import os
import sys
import threading
from pathlib import Path


def main():
    experiment=Path(__file__).resolve().parent;root=experiment.parent.parent
    sys.path.insert(0,str(experiment))
    from run_admission_proof import verify_sources
    verify_sources(root,experiment)
    if len(sys.argv)!=3 or sys.argv[2] not in ('coordinator','uni','focus','hot'):
        raise ValueError('Private admission worker arguments differ')
    folder=Path(sys.argv[1]).resolve()
    if not folder.is_relative_to((experiment/'runs').resolve()) or not folder.is_dir():
        raise ValueError('Worker directory must stay within experiment runs')
    sys.path[:0]=[str(root/'src'),str(root/'tests'),str(root/'experiments/hot_acquisition_20261017'),str(experiment)]
    import test_hot_acquisition
    from hot_proof import append_line,load_context
    from admission_proof import load_control
    mode=sys.argv[2];stop=threading.Event()
    def watcher():
        while not stop.wait(0.05):
            if (folder/'STOP').exists():stop.set()
    threading.Thread(target=watcher,daemon=True).start()
    def status(value):append_line(folder/(mode+'_status.jsonl'),dict(value,pid=os.getpid()))
    status({'status':'starting'})
    if mode=='coordinator':result=load_control(folder)[1].run(stop,on_status=status)
    else:result=load_context(folder,mode)[3].run_loop(stop,on_status=status)
    status(result);return 0


if __name__=='__main__':raise SystemExit(main())
