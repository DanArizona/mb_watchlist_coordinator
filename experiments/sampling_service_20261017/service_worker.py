"""Private bounded worker for the review runner; paths stay within its runs."""

from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path


def main():
    experiment = Path(__file__).resolve().parent
    root = experiment.parent.parent
    sys.path[:0] = [str(root / "src"), str(root / "tests"),
                   str(root / "experiments/sampling_promotion_20261016/market_data/src"),
                   str(root / "experiments/sampling_requests_20261016"), str(experiment)]
    from run_service_proof import verify_sources
    verify_sources(root, experiment)
    if len(sys.argv) != 3 or sys.argv[2] not in ("run", "after_plan", "after_commit"):
        raise ValueError("Private proof worker requires its isolated run and stage")
    folder = Path(sys.argv[1]).resolve()
    if not folder.is_relative_to((experiment / "runs").resolve()) or not folder.is_dir():
        raise ValueError("Worker directory must remain within this experiment's runs")
    from service_proof import load_service
    service = load_service(folder)[2]
    if sys.argv[2] != "run":
        stage = sys.argv[2]
        def fault(actual):
            if actual == stage:
                os._exit(73)  # deliberately bypass cleanup to test OS lock release
        service.cycle(fault_hook=fault)
        raise RuntimeError("Fault injection stage was not reached")
    stop = threading.Event()
    cycles = 0
    def status(value):
        nonlocal cycles
        cycles += 1
        write_status(dict(value, cycles=cycles, pid=os.getpid()))
        if (folder / "STOP").exists():
            stop.set()
    def write_status(value):
        # Append complete lines; Windows readers must not block atomic rename.
        with (folder / "worker_status.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(value) + "\n")
    result = service.run(stop, on_status=status)
    write_status(dict(result, cycles=cycles, pid=os.getpid()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
