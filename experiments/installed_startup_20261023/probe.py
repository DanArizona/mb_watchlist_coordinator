"""Actual installed dependency/authentication entry; no synthetic CLI mode."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
import argparse
import json
from mb_watchlist_coordinator.installed_startup_probe import ProbeSettings,run_child,run_probe

HERE=Path(__file__).resolve().parent

def main():
    expected=json.loads((HERE/'expected_mb_tools.json').read_text(encoding='utf-8'))['files']
    if len(sys.argv)==3 and sys.argv[1]=='--child':
        try:return run_child(ProbeSettings(**json.loads(sys.argv[2])),expected)
        except BaseException:return 70
    parser=argparse.ArgumentParser()
    parser.add_argument('--ecfg',type=Path,required=True)
    parser.add_argument('--output-root',type=Path,required=True)
    args=parser.parse_args()
    print('INSTALLED CLIENT: reviewed helper-source checks, one hidden password prompt, at most one SPY quote-client call.',flush=True)
    print('Startup <=8s; quote timeout 3s; parent deadline 20s plus bounded exact-child cleanup. No automatic retry.',flush=True)
    print('Normal SDK refresh may update the existing shared token database. This is transport/startup evidence, usable outside market hours.',flush=True)
    try:
        path,report=run_probe(str(args.ecfg),args.output_root,expected,
            (sys.executable,'-I','-B',str(HERE/'probe.py'),'--child'))
        print(json.dumps(report,indent=2));print('Saved report:',path)
        return 0 if report['result']=='PASS' else 1
    except KeyboardInterrupt:return 130
    except Exception:
        print('INSTALLED CLIENT: FAILED (startup_failed). No raw exception retained.')
        return 70

if __name__=='__main__':raise SystemExit(main())
