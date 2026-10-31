"""Combined daily source/manual fixture with real SQLite and native publication."""
from dataclasses import replace
from datetime import timedelta
from mb_watchlist_coordinator.daily_session import DailySession
from mb_watchlist_coordinator.operating_plan import MANUAL_PROFILE, proposed_policy
from mb_watchlist_coordinator.sampling_requests import digest,plain
import test_daily_session as legacy
from test_daily_multisymbol import large_catalog


class CombinedFixture:
    def __init__(self, *, universe_size=60, focus_size=2, root=None):
        self.case=legacy.DailySessionTests('test_preview_reads_published_anchor_and_creates_no_application_state_or_client')
        self.case.catalog_factory_override=large_catalog
        self.case.universe_symbols_override=['IBM','MSFT']+[f'C{n:04d}' for n in range(universe_size-2)]
        self.case.focus_symbols_override=self.case.universe_symbols_override[:focus_size]
        if root is not None:self.case.proof_directory_override=str(root)
        self.case.setUp()
        self.case.settings=replace(self.case.settings,policy_profile=MANUAL_PROFILE,
            policy_sha256=digest(proposed_policy(MANUAL_PROFILE)))
        self.case.session=self.session=DailySession(self.case.settings,self.case.catalog,clock=lambda:self.case.now)
        self.session.attach(create=True,publication_approved=True)
        self.session.gate.monotonic=lambda:self.case.now.timestamp()

    def close(self):self.case.doCleanups()
    def advance(self,seconds=2):self.case.now+=timedelta(seconds=seconds)
    def publish(self):
        ret=self.session.service.cycle();self.advance(1.1);return ret
    def queue_nasdaq(self,symbols,*,capture='history'):
        self.session.recovery.record(self.session.recovery.settings.queries[0],
            self.case.snapshot('HISTORICAL',[self.case.row(s,seconds=n)for n,s in enumerate(symbols)],capture))
        self.session.gate.reconcile()
    def pump(self):return self.session.gate.deliver_pending(client=self.case.client)
    def manual(self,symbol,*,target='hot',**kwargs):
        return self.session.manual.submit('promote',symbol=symbol,target=target,**kwargs)
    def feedback(self,cid):return next(r for r in self.session.manual.snapshot()['commands']if r['command_id']==cid)
