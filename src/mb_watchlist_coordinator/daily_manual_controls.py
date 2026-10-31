"""Attach manual controls to an existing owned manual-enabled daily controller.

This entry creates no daily session, starts no process, accepts no credentials
and makes no provider call. The actor/privilege are sealed by the daily profile.
An open window stays pinned to its original controller invocation across stop
or manual resume, and must be reopened for a subsequent owned invocation.
"""
from datetime import datetime, timezone
from pathlib import Path

from .daily_launch import configuration
from .daily_session import regular_path
from .daily_supervision import DailyProcessState, assert_controller_fence, read_json
from .manual_membership import ManualMembershipControls, ManualMembershipModel
from .operating_plan import MANUAL_PROFILES,BROKER_MANUAL_PROFILE
from .sampling_requests import digest


class BoundDailyManualControls(ManualMembershipControls):
    def __init__(self,*args,reader,**kwargs):
        self.reader=reader
        super().__init__(*args,**kwargs)

    def _configuration(self):
        self.reader._binding()
        super()._configuration()

    def initialize(self):
        raise ValueError('A controls window cannot initialize or reset controller state')


from .daily_identity_manual_controls import IdentityQueuedManualControls


class BoundIdentityDailyManualControls(IdentityQueuedManualControls):
    def __init__(self,*args,reader,**kwargs):
        self.reader=reader
        super().__init__(*args,**kwargs)

    def _configuration(self):
        self.reader._binding()
        super()._configuration()

    def initialize(self):
        raise ValueError('A controls window cannot initialize or reset controller state')


def open_daily_controls(state_root, *, expected_configuration_sha256, clock=None):
    from .daily_worker_view import DailyPublicationReader
    clock=clock or (lambda:datetime.now(timezone.utc))
    root=regular_path(state_root)
    raw=read_json(regular_path(root/'daily-worker.json',exists=True))
    config=configuration(raw)
    if (config.publication.policy_profile not in MANUAL_PROFILES or config.publication.state_root!=str(root)
            or digest(raw)!=expected_configuration_sha256):
        raise ValueError('Exact manual-enabled daily configuration required; p85 is not a manual session')
    driver=read_json(regular_path(root/'driver-binding.json',exists=True))
    if driver['configuration_sha256']!=expected_configuration_sha256:
        raise ValueError('Manual controller configuration binding differs')
    saved=DailyProcessState(root,driver).read()
    invocation=saved['active_invocation']
    if not saved['initialized']:
        raise ValueError('Initialized owned controller required before manual controls')
    def fence():
        if read_json(root/'daily-worker.json')!=raw:
            raise ValueError('Manual daily configuration changed')
        return assert_controller_fence(config,driver,None,invocation,clock=clock)
    reader=DailyPublicationReader(config.publication,config.catalog_path,
        binding=config.collector.daily_binding,claim=config.collector.daily_claim,
        publication_binding=config.collector.publication_binding,fence=fence,clock=clock)
    policy=reader.binding['policy']['manual_controls']
    cls=BoundIdentityDailyManualControls if config.publication.policy_profile==BROKER_MANUAL_PROFILE else BoundDailyManualControls
    controls=cls(root/'manual.sqlite3',publication=reader.service._service,
        actor_id=policy['actor_id'],allow_restrictions=policy['allow_restrictions'],clock=clock,reader=reader)
    controls.snapshot() # Read/validate existing receipts; never initialize.
    return controls


def main(argv=None):
    import argparse,json
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-root',required=True)
    parser.add_argument('--configuration-sha256',required=True)
    parser.add_argument('--once',action='store_true')
    args=parser.parse_args(argv)
    controls=open_daily_controls(args.state_root,expected_configuration_sha256=args.configuration_sha256)
    model=ManualMembershipModel(controls)
    if args.once:
        value=model.refresh();print(json.dumps(value,indent=2));return 0 if value['fresh'] else 1
    from .manual_membership_window import ManualMembershipWindow
    ManualMembershipWindow(model).run()
    return 0


if __name__=='__main__':
    raise SystemExit(main())
