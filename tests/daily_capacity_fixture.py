"""Cold owned collector at a seeded full history. Synthetic credentials only."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys
import threading
import time
from uuid import uuid4

from mb_watchlist_coordinator.authenticated_startup import AuthStartupSettings,SessionPassword
from mb_watchlist_coordinator.daily_controller import DailyController
from mb_watchlist_coordinator.daily_supervision import DailyManagedWorker,sealed,read_json
from mb_watchlist_coordinator.recovery_workers import atomic_json
from mb_watchlist_coordinator.sampling_requests import digest,utc_text
from mb_watchlist_coordinator.sampling_service import owner_lock
from mb_watchlist_coordinator.daily_supervision import DailyWorkerConfiguration
from mb_watchlist_coordinator.supervised_hot_worker import progress_path,progress_receipt


def owned_cold_startup(case,collector_settings):
    real=datetime.now(timezone.utc);logical=case.now
    clock=lambda:logical+(datetime.now(timezone.utc)-real)
    config=DailyWorkerConfiguration(case.session.settings,str(case.root/'catalog'),collector_settings,
        AuthStartupSettings(str(case.root/'unused.ecfg'),collector_settings.stop_at_utc))
    import mb_market_data
    scene=case.root/'capacity-startup-scene.json'
    atomic_json(scene,{'real_anchor':real.isoformat(),'logical_anchor':logical.isoformat(),
        'native_src':str(Path(mb_market_data.__file__).resolve().parents[1]),
        'log':str(case.root/'capacity-startup-events.jsonl')})
    entry=str(Path(__file__).parent/'fixtures/daily_authenticated_process.py')
    root=Path(config.publication.state_root)
    commands={role:(sys.executable,'-I','-B',entry,str(scene),role,str(root/'daily-worker.json'))
        for role in ('collector','identity','report')}
    password=SessionPassword('SYNTHETIC-PRIVATE-CANARY-62',digest(config.payload()))
    controller=DailyController(case.session,config,commands=commands,password=password,
        clock=clock,activation_approved=True)
    binding=controller.identity;invocation=uuid4().hex
    finished=threading.Event();worker=None
    result={'contract':'full-history-owned-cold-startup-v1','result':'FAILED',
        'actual_vault_access':False,'actual_broker_sdk_used':False,'network':'denied',
        'original_progress_deadline_seconds':3,'synthetic_sdk_only':True,
        'seeded_hot_acquisitions':9358,'provider_capacity_qualified':False}
    def live():
        atomic_json(root/'driver-live.json',sealed({'contract':binding['contract'],
            'identity_sha256':digest(binding),'invocation':invocation,
            'observed_at_utc':utc_text(clock()),'state':'RUNNING'}))
    try:
        with owner_lock(root/'driver-owner.lock'):
            atomic_json(root/'driver-binding.json',binding);atomic_json(root/'daily-worker.json',config.payload())
            controller.state.create()
            controller.state.change(lambda state:state.update(initialized=True,active_invocation=invocation,
                invocations=[{'invocation':invocation,'at_utc':utc_text(clock()),'manual_resume':False}]))
            live()
            def refresh():
                while not finished.wait(.2):live()
            thread=threading.Thread(target=refresh,daemon=True);thread.start()
            worker=DailyManagedWorker(root/'workers',command=commands['collector'],binding=binding,
                state=controller.state,password=password,clock=clock)
            began=time.monotonic()
            worker.ensure(start_allowed=True,resume_after_utc=clock().isoformat())
            job=worker._job();result['job']=job
            while time.monotonic()-began<4:
                if progress_path(job).exists():
                    receipt=progress_receipt(job);result['progress']=receipt
                    if receipt['status']=='first_completed_work_observed':
                        elapsed=(datetime.fromisoformat(receipt['observed_at_utc'])-
                            datetime.fromisoformat(job['started_at_utc'])).total_seconds()
                        result['job_to_first_native_work_seconds']=elapsed
                        result['result']='PASS' if elapsed<3 else 'FAILED'
                    break
                if worker.child.poll() is not None:break
                time.sleep(.005)
            result['observed_elapsed_seconds']=time.monotonic()-began
            result['cleanup']=worker.stop_owned(reason='synthetic_cold_startup_complete')
            finished.set();thread.join(timeout=1)
    finally:
        finished.set()
        if worker is not None and worker.child is not None and worker.child.poll() is None:
            worker.stop_owned(reason='synthetic_cold_startup_cleanup')
        password.close()
        atomic_json(case.root/'owned-cold-startup-proof.json',result)
    return result
