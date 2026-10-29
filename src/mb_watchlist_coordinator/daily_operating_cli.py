"""Operator review/status/stop commands. No activation or installation command."""
import argparse
import json


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    review=commands.add_parser('review',help='Describe a candidate using saved published inputs')
    for name in ('opening-proposal','focus-proposal','journal','catalog-root','state-root','ecfg'):
        review.add_argument('--'+name,required=True)
    outer=commands.add_parser('outer-status',help='Read independently owned daily status')
    outer.add_argument('--outer-root',required=True)
    hot=commands.add_parser('hot-status',help='Read saved Hot membership/collection status')
    hot.add_argument('--state-root',required=True)
    stop=commands.add_parser('stop',help='Request a bound cooperative stop of this outer invocation')
    stop.add_argument('--outer-root',required=True)
    args=parser.parse_args(argv)
    if args.command=='review':
        from .daily_operating_review import build_operating_review
        result=build_operating_review(args.opening_proposal,args.focus_proposal,
            journal=args.journal,catalog=args.catalog_root,state_root=args.state_root,ecfg=args.ecfg)
    elif args.command=='outer-status':
        from .daily_operating import inspect_operating_status
        result=inspect_operating_status(args.outer_root)
    elif args.command=='hot-status':
        from .daily_hot_status import inspect_hot_status
        result=inspect_hot_status(args.state_root)
    else:
        from .daily_operating import request_stop
        result=request_stop(args.outer_root)
    print(json.dumps(result,indent=2))
    return 0


if __name__=='__main__':raise SystemExit(main())
