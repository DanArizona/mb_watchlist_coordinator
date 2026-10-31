"""Isolated advancing-clock tail measurements; synthetic SDK, actual CPU time."""
from dataclasses import replace
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import socket
import time
from unittest.mock import patch


def run(root=None):
    def denied(*args,**kwargs):raise OSError('Network denied in multi-symbol timing proof')
    socket.socket.connect=socket.socket.connect_ex=socket.create_connection=socket.getaddrinfo=denied
    from test_daily_multisymbol import MultiNativeTests,SYMBOLS,replay_identity
    from mb_market_data.quote_journal_audit import audit_quote_journal
    c=MultiNativeTests('test_actual_native_batches_follow_forty_admissions_and_overflow_with_audit_and_replay')
    c.setUp()
    try:
        c.f.queue(SYMBOLS[:40])
        for n in range(40):
            c.f.pump();c.f.advance()
            if n%10==9:print(json.dumps({'phase':'admissions','authorized':n+1}),flush=True)
        c.collector.close()
        c.settings=replace(c.settings,start_at_utc=(c.c.now+timedelta(seconds=1)).isoformat())
        c.collector=c.make()
        # Match run_collector: authenticate/set the owned client before prepare.
        c.collector.client=c.factory()
        c.collector.prepare(create=True)
        measurements=[]
        for _ in range(3):
            logical=c.collector.next.scheduled_at+timedelta(milliseconds=50)
            began=time.perf_counter()
            clock=lambda:logical+timedelta(seconds=time.perf_counter()-began)
            c.c.now=logical;c.collector.clock=clock;c.collector.poller.clock=clock;c.s.clock=clock
            class Clock(datetime):
                @classmethod
                def now(cls,tz=None):return clock().astimezone(tz or timezone.utc)
            with patch('mb_market_data.schwab_quotes.datetime',Clock):result=c.collector.tick()
            elapsed=time.perf_counter()-began
            c.c.now=clock()
            measurements.append({'native_tick_seconds':elapsed,**result})
            print(json.dumps({'phase':'elapsed_native_tick','measurement':measurements[-1]}),flush=True)
            if result['status']!='acquired':break
        audit=audit_quote_journal(c.c.journal,audited_at=c.c.now)
        replay1,replay2=replay_identity(c.c.journal),replay_identity(c.c.journal)
        report={'contract':'multi-symbol-advancing-tail-proof-v1',
            'result':'PASS' if len(measurements)==3 and all(m['status']=='acquired' and
                m['native_tick_seconds']<2 and m['before_api_gate_seconds']<=.75 for m in measurements)
                and audit.passed and replay1==replay2 else 'FAILED',
            'clock':'logical inter-slot positioning; actual elapsed native tick and provider gates',
            'maximum_members':{'uni':640,'focus':80,'hot':40},
            'identity_calls':len(c.c.calls),'measurements':measurements,
            'native_audit_passed':audit.passed,'two_fresh_replays_equal':replay1==replay2,
            'first_replay':replay1,'synthetic_only':True,'network':'denied',
            'provider_capacity_qualified':False,'retained_full_size_history_qualified':False,
            'full_elapsed_paced_composition_qualified':False}
        if root is not None:
            root=Path(root);root.mkdir(parents=True,exist_ok=False)
            (root/'timing.json').write_text(json.dumps(report,indent=2)+'\n')
        return report
    finally:c.doCleanups()


if __name__=='__main__':
    print(json.dumps(run(),indent=2))
