"""Fabricated credentials and explicit clocks for manual-reopen qualification."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from types import SimpleNamespace

from runtime_fixtures import RuntimeFixture, ScriptedFeed, SECRET, Response
from runtime_process_evidence import subsequent_halt_snapshot
from mb_watchlist_coordinator.controller_resume import ResumeSettings, resume_manual
from mb_watchlist_coordinator.integrated_runtime import IntegratedRuntime
from mb_watchlist_coordinator.sampling_requests import digest, utc_text


class ResumeFixture(RuntimeFixture):
    def __init__(self, root):
        super().__init__(root)
        self.runtime = IntegratedRuntime(self.session, feed_client=ScriptedFeed(self.session.feed),
            worker_command=('synthetic-worker-not-started-by-logical-tests',))
        self.runtime.initialize()
        self.runtime.worker.ensure = lambda **kw: {'status':'RUNNING','synthetic_worker':True}
        self.auth_calls = []; self.resume_mode = 'normal'; self.client_closes = 0
        self.resume_constructor = None
        self.resumed = []

    def activate(self):
        self.now = self.start
        self.runtime.step()

    def halt(self):
        if not self.session.live.snapshot()['receipts']: self.activate()
        self.now = self.start+timedelta(seconds=1)
        baseline = self.session.live.snapshot()['receipts'][0]['snapshot']
        self.session.live.record_snapshot(subsequent_halt_snapshot(baseline,
            observed_at=self.now,capture_id='manual-resume-synthetic-halt'))
        self.runtime.step()
        self.now = self.start+timedelta(seconds=3)

    def stop_original(self):
        if not self.runtime.closed:
            self.now = max(self.now,self.start+timedelta(seconds=5))
            self.runtime.close()

    def settings_for_resume(self, nonce='b'*32):
        return ResumeSettings(str(self.target),self.session.plan.configuration_sha256,
            digest(self.runtime.identity),utc_text(self.clock()),nonce,self.runtime.command)

    def api(self):
        f = self
        def load(path,password):
            f.auth_calls.append('load')
            if bytes(password)!=SECRET.encode():raise ValueError('Synthetic password mismatch')
            if f.resume_mode=='load_error':raise RuntimeError(SECRET)
            return object()
        def status(config,*,observed_at):
            f.auth_calls.append('status')
            def require(required):
                assert required==f.stop+timedelta(minutes=75,seconds=30)
                if f.resume_mode=='horizon' or f.resume_mode=='post_horizon' and f.auth_calls.count('status')==2:
                    raise RuntimeError(SECRET)
            return SimpleNamespace(require_refresh_valid_through=require)
        def make(config,*,timeout,call_on_auth):
            f.auth_calls.append('construct');assert timeout==3
            if f.resume_constructor:f.resume_constructor()
            if f.resume_mode=='authorization':call_on_auth('https://synthetic.invalid?code='+SECRET)
            class Client:
                def quotes(self,symbols,*,fields):
                    f.auth_calls.append(('quote',list(symbols),fields))
                    return Response(symbols[0])
                def close(self):f.client_closes+=1
            return Client()
        return SimpleNamespace(load_secure_schwab_config=load,read_schwab_token_status=status,
            make_client_from_config=make,DEFAULT_POLLING_REFRESH_MARGIN=timedelta(minutes=75,seconds=30))

    def reopen(self,nonce='b'*32,**kwargs):
        self.stop_original();self.input_password=bytearray(SECRET.encode())
        settings=kwargs.pop('settings',self.settings_for_resume(nonce))
        value=resume_manual(settings,self.input_password,clock=self.clock,
            inventory=lambda _: {'qualified':True,'reason':'probe_pass','synthetic_only':True},
            secure_api=self.api(),feed_factory=ScriptedFeed,**kwargs)
        self.resumed.append(value)
        return value

    def runs(self):
        with closing(sqlite3.connect(self.session.store.database_path)) as c:
            return c.execute('SELECT count(*) FROM poll_run').fetchone()[0]

    def close(self):
        for value in self.resumed:
            if not value.closed:value.close()
        self.runtime.close();self.session.close()

