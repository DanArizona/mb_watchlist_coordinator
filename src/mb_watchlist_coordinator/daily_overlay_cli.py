"""Read-only snapshot or loopback viewer; no startup, credential or edit verbs."""
import argparse
import json
from pathlib import Path
import threading
import webbrowser

from .daily_overlay import DailyOverlayReader, DailyOverlayModel
from .daily_supervision import read_json


def reader_from_arguments(args):
    journal=None
    if args.operating_summary:
        summary=read_json(Path(args.operating_summary).resolve())
        if (summary['contract']!='daily-hot-operator-delivery-v1'
                or summary['result']!='PREPARED_NOT_ACTIVATED'):
            raise ValueError('Original generated operating summary required')
        root=summary['state_root'];journal=summary['journal_path']
    else:root=args.state_root
    return DailyOverlayReader(Path(root).resolve(),candle_directory=args.candle_directory,expected_journal=journal)


def serve(model, *, symbol=None, port=8056, open_browser=True, stop_event=None, banner_note=None):
    from .daily_overlay_view import create_daily_overlay_dashboard
    from mb_market_data.local_dashboard_server import LocalDashboardServer
    stop=stop_event or threading.Event()
    app=create_daily_overlay_dashboard(model,initial_symbol=symbol,request_display_stop=stop.set,banner_note=banner_note)
    server=LocalDashboardServer(app.server,host='127.0.0.1',port=port,stop_event=stop)
    url=f'http://127.0.0.1:{server.bound_port}'
    print('Read-only daily Overlay: '+url,flush=True)
    print('Stop display or Ctrl+C closes only this viewer. Collectors continue.',flush=True)
    if open_browser:webbrowser.open(url)
    server.serve_until_stopped()


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('snapshot','view'))
    location=parser.add_mutually_exclusive_group(required=True)
    location.add_argument('--state-root');location.add_argument('--operating-summary')
    parser.add_argument('--symbol');parser.add_argument('--candle-directory')
    parser.add_argument('--port',type=int,default=8056)
    parser.add_argument('--no-browser',action='store_true')
    args=parser.parse_args(argv)
    if not 0<=args.port<=65535:parser.error('Port must be between 0 and 65535')
    try:
        model=DailyOverlayModel(reader_from_arguments(args))
        if args.command=='snapshot':
            r=model.refresh(args.symbol)
            print(json.dumps({'fresh':r.fresh,'error':r.error,
                'snapshot':r.snapshot.summary() if r.snapshot else None},indent=2))
            return 0 if r.fresh else 1
        serve(model,symbol=args.symbol,port=args.port,open_browser=not args.no_browser)
        return 0
    except (OSError,ValueError,TypeError,KeyError) as e:
        print('Read-only Overlay unavailable: '+type(e).__name__)
        return 1


if __name__=='__main__':raise SystemExit(main())
