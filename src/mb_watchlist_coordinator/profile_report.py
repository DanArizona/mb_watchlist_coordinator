"""Read-only reconstruction for a separately bounded reporting child.

No encrypted config/token database is opened; no client, native poll_run,
request, publication, acquisition or source attempt is created.
"""
import json
from pathlib import Path
from types import SimpleNamespace

from .controller_resume import ResumeSettings, _restore
from .integrated_runtime import _PreparedDelivery, _RuntimeWorker
from .nasdaq_feed_recovery import BoundedFeedClient
from .nasdaq_recovery_supervisor import NasdaqRecoverySupervisor
from .recovery_workers import ManagedRecoveryWorker
from .sampling_requests import digest,timestamp,plain
from .profile_runtime import BoundProfile


def report_saved_profile(root, *, outer_stop_path, nonce):
    root=Path(root).resolve()
    outer=json.loads(Path(outer_stop_path).read_text())
    if set(outer)!={'nonce','reason','acquisition_stop_requested_at_utc'} or outer['nonce']!=nonce:
        raise ValueError('Outer stop binding differs')
    stop=timestamp(outer['acquisition_stop_requested_at_utc'])
    binding=json.loads((root/'runtime-binding.json').read_text())
    settings=ResumeSettings(str(root),binding['configuration_sha256'],digest(binding),stop.isoformat(),
        digest({'reporting_nonce':nonce})[:32],tuple(binding['worker_command']))
    settings.public()
    session,saved=_restore(settings,lambda:stop)
    # Restore only the public read graph. The prepared client stays None.
    runtime=SimpleNamespace(root=root,identity=saved,start=timestamp(saved['start_at_utc']),
        stop=timestamp(saved['stop_at_utc']),session=session,closed=True,clock=lambda:stop)
    runtime.managed=ManagedRecoveryWorker(root/'workers',role='experimental_hot',command=settings.worker_command,
        binding=plain(session.service.identity),max_starts=3,startup_seconds=3,stale_seconds=3,clock=runtime.clock,
        startup_handoff=SimpleNamespace(identity={'contract':'anonymous-stdin-secret-v1',
            'configuration_sha256':saved['worker_configuration_sha256']}))
    runtime.authority=NasdaqRecoverySupervisor(root/'runtime.sqlite3',feed_client=BoundedFeedClient(session.feed),
        delivery=_PreparedDelivery(runtime,session.gated_delivery),service=session.service,
        worker=_RuntimeWorker(runtime,runtime.managed),clock=runtime.clock)
    profile=BoundProfile.__new__(BoundProfile)
    profile.path=root/'profile.json';state=json.loads(profile.path.read_text());profile.profile=state['binding']['profile']
    profile.runtime=runtime
    profile.binding={'contract':'bounded-hot-profile-state-v1','profile':profile.profile,
        'runtime_sha256':digest(saved),'start_at_utc':saved['start_at_utc'],'stop_at_utc':saved['stop_at_utc']}
    events=profile._events()
    if 'stop' not in events:
        # A killed controller cannot fabricate a cooperative stop or goal.
        facts,_=profile.facts()
        from .profile_evidence import final_native_report
        report=final_native_report(session,profile=profile.profile,facts=facts,
            stop_at_utc=stop.isoformat(),cutover_at_utc=events.get('cutover',{}).get('data',{}).get('at_utc'),
            source_reconciled=False,source_reasons=['controller_stop_receipt_missing'],
            fault=events.get('fault',{}).get('data'),restart=events.get('restart',{}).get('data'))
    else:
        controller_stop=timestamp(events['stop']['data']['requested_at_utc'])
        # The outer's first stop request may precede the child's cooperative
        # receipt. Audit that earlier endpoint; do not grant cleanup-time goals.
        report=profile.evidence(stop_at_utc=min(controller_stop,stop).isoformat())
        report['controller_stop_requested_at_utc']=controller_stop.isoformat()
    report.update(runtime_sha256=digest(saved),outer_nonce=nonce,
        preflight_configuration_sha256=session.receipt['preflight_configuration_sha256'],
        outer_stop_requested_at_utc=outer['acquisition_stop_requested_at_utc'],
        credential_access=False,reporting_read_only=True)
    return report
