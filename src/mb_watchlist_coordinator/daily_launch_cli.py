"""Daily Hot catalog, review and explicitly approved launch commands."""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from .authenticated_startup import StartupError


def main(source_root, argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    catalog = commands.add_parser('catalog', help='Acquire two public directory files; no password or broker')
    catalog.add_argument('--catalog-root', required=True)
    review = commands.add_parser('review', help='Read saved inputs and dependencies; no password or API')
    for name in ('opening-proposal', 'focus-proposal', 'journal', 'catalog-root', 'state-root', 'ecfg', 'outer-root'):
        review.add_argument('--'+name, required=True)
    review.add_argument('--mode', choices=('fresh', 'manual_resume'), default='fresh')
    review.add_argument('--previous-outer')
    review.add_argument('--output', required=True, help='Create a new public review JSON')
    run = commands.add_parser('run', help='Run only after approval of the exact review and its limits')
    run.add_argument('--review', required=True)
    run.add_argument('--approved-review-sha256', required=True)
    run.add_argument('--activation-approved', action='store_true')
    outer_status = commands.add_parser('outer-status', help='Read outer status without a broker request')
    outer_status.add_argument('--outer-root', required=True)
    hot_status = commands.add_parser('hot-status', help='Read saved Hot membership, collection and incidents')
    hot_status.add_argument('--state-root', required=True)
    stop = commands.add_parser('stop', help='Cooperatively stop only this owned Hot invocation')
    stop.add_argument('--outer-root', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'catalog':
            from .daily_session import regular_path
            from .integrated_catalog import acquire_catalog
            path = regular_path(args.catalog_root)
            if path.exists() or not path.parent.is_dir() or not path.name.startswith('daily_catalog_'):
                raise ValueError('New separate daily_catalog_ directory required')
            directory = acquire_catalog(deadline=datetime.now(timezone.utc)+timedelta(seconds=60), allow_network=True)
            saved = directory.persist(path)
            result = {'status': 'SAVED', 'catalog_root': str(saved.path), 'catalog_id': saved.catalog_id,
                'symbols': len(saved.symbols), 'directory_requests': 2,
                'actual_vault_access': False, 'broker_access': False, 'production_changes': False}
        elif args.command == 'review':
            from .daily_launch import build_launch_review
            from .daily_session import regular_path
            result = build_launch_review(source_root, args.opening_proposal, args.focus_proposal,
                journal=args.journal, catalog=args.catalog_root, state_root=args.state_root,
                ecfg=args.ecfg, outer_root=args.outer_root, mode=args.mode, previous_outer=args.previous_outer)
            with regular_path(args.output).open('x', encoding='utf-8') as out:
                out.write(json.dumps(result, indent=2)+'\n')
        elif args.command == 'run':
            from .daily_launch import run_launch
            from .daily_supervision import read_json
            result = run_launch(read_json(Path(args.review)),
                approved_review_sha256=args.approved_review_sha256,
                activation_approved=args.activation_approved)
        elif args.command == 'outer-status':
            from .daily_operating import inspect_operating_status
            result = inspect_operating_status(args.outer_root)
        elif args.command == 'hot-status':
            from .daily_hot_status import inspect_hot_status
            result = inspect_hot_status(args.state_root)
        else:
            from .daily_operating import request_stop
            result = request_stop(args.outer_root)
        print(json.dumps(result, indent=2))
        return 0 if result.get('result', 'STOPPED') == 'STOPPED' else 1
    except KeyboardInterrupt:
        return 130
    except StartupError as error:
        print('Daily launch refused:', error.code)
        return 70
    except Exception as error:
        print('Daily launch refused:', type(error).__name__)
        return 70
