"""Fixed profile goals layered over the accepted IntegratedRuntime API.

This adapter neither authenticates nor chooses feed/worker commands. Its caller
must supply the already bound runtime, inside an owned outer process scope.
"""
import json
from pathlib import Path
import time

from .controller_resume import _generation_history, _counts
from .profile_evidence import native_facts, goal_counts, final_native_report, PROFILES
from .recovery_workers import atomic_json
from .sampling_requests import digest, plain, timestamp, utc_text


class BoundProfile:
    def __init__(self, runtime, profile, *, monotonic=time.monotonic):
        if profile not in PROFILES or not runtime.initialized or runtime.closed:
            raise ValueError('Initialized runtime and explicit profile required')
        self.runtime,self.profile,self.monotonic=runtime,profile,monotonic
        self.path=runtime.root/'profile.json'
        self.binding={'contract':'bounded-hot-profile-state-v1','profile':profile,
            'runtime_sha256':digest(runtime.identity),'start_at_utc':utc_text(runtime.start),
            'stop_at_utc':utc_text(runtime.stop)}
        self.hold_until=None
        if self.path.exists():
            self._read()
        else:atomic_json(self.path,{'binding':self.binding,'events':[]})
        self.original_ensure=runtime.worker.ensure
        runtime.worker.ensure=self._ensure

    def _read(self):
        if self.path.is_symlink():raise ValueError('Profile state cannot be a link')
        value=json.loads(self.path.read_text())
        if set(value)!={'binding','events'} or value['binding']!=self.binding:
            raise ValueError('Original profile binding differs')
        previous=digest(self.binding);seen=set();last=None
        for i,e in enumerate(value['events'],1):
            body=dict(e);sha=body.pop('sha256')
            at=timestamp(e['at_utc'])
            if (e['sequence']!=i or e['previous_sha256']!=previous or digest(body)!=sha
                    or e['kind'] not in ('cutover','fault_intent','fault','restart','stop') or e['kind'] in seen
                    or last is not None and at<last):raise ValueError('Profile event prefix differs')
            required={'fault_intent':'cutover','fault':'fault_intent','restart':'fault'}.get(e['kind'])
            if ('stop' in seen or required and required not in seen
                    or self.profile=='ordinary' and e['kind'] in ('fault_intent','fault','restart')):
                raise ValueError('Profile action order differs')
            seen.add(e['kind']);previous=sha;last=at
        return value

    def _events(self):return {e['kind']:e for e in self._read()['events']}

    def _append(self,kind,data):
        value=self._read();events=value['events']
        seen={e['kind'] for e in events}
        required={'fault_intent':'cutover','fault':'fault_intent','restart':'fault'}.get(kind)
        if (kind in seen or 'stop' in seen or required and required not in seen
                or self.profile=='ordinary' and kind in ('fault_intent','fault','restart')):
            raise ValueError('Duplicate, stopped or out-of-order profile action')
        e={'sequence':len(events)+1,'kind':kind,'at_utc':utc_text(self.runtime.clock()),
            'previous_sha256':events[-1]['sha256'] if events else digest(self.binding),'data':data}
        e['sha256']=digest(e);events.append(e);atomic_json(self.path,value)

    def _ensure(self, *, start_allowed, resume_after_utc):
        events=self._events();fault=events.get('fault');restart=events.get('restart')
        if 'fault_intent' in events and not fault:
            return {'status':'BLOCKED','reason':'profile_fault_outcome_unknown'}
        if fault and not restart:
            data=fault['data']
            if self.hold_until is None:
                # Reopening never shortens the original persisted 15s hold.
                remaining=max(0,15-(self.runtime.clock()-timestamp(data['exit_observed_at_utc'])).total_seconds())
                self.hold_until=self.monotonic()+remaining
            held=(self.monotonic()<self.hold_until or
                (self.runtime.clock()-timestamp(data['exit_observed_at_utc'])).total_seconds()<15)
            if held:
                if self.runtime.managed.child is not None:raise ValueError('Replacement appeared during fault hold')
                return {'status':'WAITING_FOR_PROFILE_HOLD'}
        return self.original_ensure(start_allowed=start_allowed,resume_after_utc=resume_after_utc)

    def facts(self):
        managed=self.runtime.managed
        if (digest(self.runtime.identity)!=self.binding['runtime_sha256']
                or json.loads((self.runtime.root/'runtime-binding.json').read_text())!=plain(self.runtime.identity)):
            raise ValueError('Original profile runtime identity differs')
        _generation_history(managed)
        counts=_counts(self.runtime.session,managed)
        if any(counts[k]>limit for k,limit in (('hot_quote_permits',60),('identity_quote_permits',3),
                ('directory_source_permits',2),('feed_attempts',10),('worker_starts',3))):
            raise ValueError('Original cumulative profile budget exceeded')
        jobs=sorted((json.loads(p.read_text()) for p in managed.root.glob('*.job.json')),key=lambda j:j['generation'])
        def generation(a):
            candidates=[j for j in jobs if timestamp(j['started_at_utc'])<=a.dispatched_at_utc]
            if not candidates:raise ValueError('Native acquisition has no registered worker generation')
            j=candidates[-1]
            if a.scheduled_at_utc<timestamp(j['first_eligible_slot_utc']):
                raise ValueError('Acquisition precedes generation future-slot gate')
            return j['generation']
        facts,state=native_facts(self.runtime.session,generation_for=generation)
        if any(f['symbols']!=[counts['selected_symbol']] for f in facts):
            raise ValueError('Native roster differs from the selected symbol')
        return facts,state

    def step(self, *, synthetic=None):
        r=self.runtime;events=self._events()
        if 'stop' in events:return {'status':'STOPPED','profile':self.profile}
        report=r.step(synthetic=synthetic)
        if r.closed:return {'status':'RUNTIME_STOPPED','runtime_reason':report.get('reason')}
        events=self._events()
        if report.get('discovery_scope_reconciled') and 'cutover' not in events:
            feed=r.session.feed.snapshot()
            dated=[timestamp(a['completed_at_utc']) for a in feed['attempts'] if a['query_id']!='CURRENT' and a['outcome']['status']=='valid']
            current=[a for a in feed['attempts'] if a['query_id']=='CURRENT' and a['outcome']['status']=='valid']
            last=current[-1] if current else None
            if not dated or last is None or timestamp(last['completed_at_utc'])<=max(dated):
                raise ValueError('A strictly later valid CURRENT cutover is required')
            self._append('cutover',{'at_utc':last['completed_at_utc'],'attempt_id':last['attempt_id'],
                'feed_head_sha256':feed['head_sha256']})
            events=self._events()
        from mb_market_data.sampling_acquisition import AcquisitionBusy
        try:facts,state=self.facts()
        except AcquisitionBusy:
            # An active writer owns the native snapshot. Observe on the next
            # bounded pump turn; do not repeat a provider call or renew a gate.
            return {'status':'OBSERVING','profile':self.profile,'native_snapshot_pending':True}
        fault=events.get('fault',{}).get('data');restart=events.get('restart',{}).get('data')
        cutover=events.get('cutover',{}).get('data',{}).get('at_utc')
        if fault and not restart and report.get('worker',{}).get('status')=='RUNNING':
            job=r.managed._job();first=report['worker'].get('first_completed_work')
            if not first:raise ValueError('Replacement has no verified completed work')
            restart={'generation':job['generation'],'token':job['token'],'pid':r.managed.child.pid,
                'started_at_utc':job['started_at_utc'],'ready_at_utc':first['observed_at_utc'],
                'first_eligible_slot_utc':job['first_eligible_slot_utc']}
            goal_counts(self.profile,facts,cutover_at_utc=cutover,fault=fault,restart=restart)
            self._append('restart',restart)
        if self.profile=='owned_worker_recovery' and cutover and not fault:
            good=[f for f in facts if f['quote'] and timestamp(f['scheduled_at_utc'])>timestamp(cutover)]
            if len(good)>=12:
                job=r.managed._job();child=r.managed.child
                if child is None or child.poll() is not None:raise ValueError('Fault target is not the exact owned live child')
                fault={'generation':job['generation'],'token':job['token'],'pid':child.pid,
                    'last_acknowledged_id':good[-1]['id'],'requested_at_utc':utc_text(r.clock())}
                # Charge the one permitted fault BEFORE touching the child.
                # An interrupted action is unknown, never automatically repeated.
                self._append('fault_intent',dict(fault))
                child.terminate();child.wait(timeout=2)
                fault['exit_observed_at_utc']=utc_text(r.clock())
                self.hold_until=self.monotonic()+15
                # Reap the exact owned handle and preserve its normal exit receipt.
                r.managed._reap_owned('profile_injected_fault')
                self._append('fault',fault)
        counts=goal_counts(self.profile,facts,cutover_at_utc=cutover,fault=fault,restart=restart)
        return {'status':'GOAL_COMPLETE' if counts['goal_complete'] else 'OBSERVING',
            'profile':self.profile,'counts':counts,'source_reconciled':bool(report.get('discovery_scope_reconciled')),
            'native_pending':state['pending'] is not None}

    def close(self, *, reason='operator_stop'):
        from .integrated_runtime import CLOSE_REASONS
        reason=reason if reason in CLOSE_REASONS else 'runtime_integrity_or_driver_failure'
        r=self.runtime
        if 'stop' not in self._events():self._append('stop',{'requested_at_utc':utc_text(r.clock()),'reason':reason})
        return r.close(reason=reason)

    def evidence(self, *, stop_at_utc=None):
        r=self.runtime;events=self._events()
        if not r.closed or 'stop' not in events:raise ValueError('Stop owned work before final reporting')
        self.verify_receipts(events)
        facts,state=self.facts()
        last=plain(r.authority.snapshot())['last_report'] or {}
        recorded=events['stop']['data']['requested_at_utc']
        endpoint=recorded if stop_at_utc is None else stop_at_utc
        if not timestamp(r.session.plan.settings.password_submitted_at_utc)<=timestamp(endpoint)<=timestamp(recorded):
            raise ValueError('Reporting endpoint cannot extend the recorded stop')
        return final_native_report(r.session,profile=self.profile,facts=facts,
            stop_at_utc=endpoint,
            cutover_at_utc=events.get('cutover',{}).get('data',{}).get('at_utc'),
            source_reconciled=bool(last.get('discovery_scope_reconciled')),
            source_reasons=last.get('reasons',()),fault=events.get('fault',{}).get('data'),
            restart=events.get('restart',{}).get('data'))

    def verify_receipts(self,events):
        r=self.runtime
        if 'fault_intent' in events and 'fault' not in events:
            raise ValueError('Profile fault outcome is unknown; it cannot be repeated')
        if 'cutover' in events:
            c=events['cutover']['data'];feed=r.session.feed.snapshot()
            a=next((a for a in feed['attempts'] if a['attempt_id']==c['attempt_id']),None)
            prefix={e['event_sha256']:e['sequence'] for e in feed['events']}
            head=prefix.get(c['feed_head_sha256'],0)
            earlier=[a for a in feed['attempts'] if a['query_id']!='CURRENT' and a['outcome']['status']=='valid'
                and prefix[a['completion_event_sha256']]<=head and timestamp(a['completed_at_utc'])<timestamp(c['at_utc'])]
            if (a is None or a['query_id']!='CURRENT' or a['outcome']['status']!='valid'
                    or a['completed_at_utc']!=c['at_utc']
                    or prefix[a['completion_event_sha256']]>head
                    or not all(q.query_id in {a['query_id'] for a in earlier} for q in r.session.feed.queries)):
                raise ValueError('Profile cutover receipt no longer matches the feed')
        if 'fault' in events:
            f=events['fault']['data']
            if events['fault_intent']['data']!={k:v for k,v in f.items() if k!='exit_observed_at_utc'}:
                raise ValueError('Profile fault intent and exit differ')
            exit=json.loads((r.managed.root/(f['token']+'.exit.json')).read_text())
            if (exit['token']!=f['token'] or exit['pid']!=f['pid'] or exit['returncode'] is None
                    or exit['reason']!='profile_injected_fault'
                    or timestamp(exit['observed_at_utc'])<timestamp(f['exit_observed_at_utc'])):
                raise ValueError('Profile fault has no matching owned exit receipt')
        if 'restart' in events:
            from .supervised_hot_worker import progress_receipt
            new=events['restart']['data']
            job=json.loads((r.managed.root/(new['token']+'.job.json')).read_text())
            first=progress_receipt(job)
            if (job['generation']!=new['generation'] or job['started_at_utc']!=new['started_at_utc']
                    or job['first_eligible_slot_utc']!=new['first_eligible_slot_utc']
                    or first['pid']!=new['pid'] or first['observed_at_utc']!=new['ready_at_utc']
                    or first['status']!='first_completed_work_observed'):
                raise ValueError('Profile replacement progress differs')
