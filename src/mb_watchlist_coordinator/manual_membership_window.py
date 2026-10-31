"""Persistent manual membership controls for a trusted, explicitly bound backend."""
from concurrent.futures import ThreadPoolExecutor
import time
from uuid import uuid4


class ManualMembershipWindow:
    def __init__(self, model, *, title='MasterBot manual membership', interval_ms=1000):
        import tkinter as tk
        from tkinter import ttk
        self.model, self.interval_ms = model, interval_ms
        self.root = tk.Tk()
        self.root.title(title); self.root.geometry('1180x690'); self.root.minsize(940, 530)
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='manual-membership')
        self.future, self.operation, self.started = None, None, None
        self.pending_action, self.button_states = None, {}
        self.closed, self.last_value, self.read_count = False, None, 0
        self.last_rows = None
        outer = ttk.Frame(self.root, padding=14); outer.pack(fill='both', expand=True)
        self.banner = ttk.Label(outer, text='Reading verified membership...', font=('Segoe UI', 12, 'bold'))
        self.banner.pack(anchor='w', fill='x')
        self.context = ttk.Label(outer, text='', wraplength=1100); self.context.pack(anchor='w', pady=6)
        ttk.Label(outer, text='Own demotion/withdrawal changes your demand. Other sources and stabilization rules can retain higher membership.',
                  wraplength=1100).pack(anchor='w')
        editor = ttk.Frame(outer); editor.pack(fill='x', pady=10)
        ttk.Label(editor, text='Symbol').pack(side='left')
        self.symbol = tk.StringVar()
        ttk.Entry(editor, textvariable=self.symbol, width=16).pack(side='left', padx=(5, 15))
        ttk.Label(editor, text='Reason (optional)').pack(side='left')
        self.reason = tk.StringVar()
        ttk.Entry(editor, textvariable=self.reason, width=48).pack(side='left', padx=5)
        self.buttons = {}
        for name, label, target in [('focus', 'Request Focus', 'focus'), ('hot', 'Request Hot', 'hot')]:
            button = ttk.Button(editor, text=label, command=lambda t=target: self.submit('promote', target=t))
            button.pack(side='left', padx=4); self.buttons[name] = button
        self.action_text = ttk.Label(outer, text='No action submitted.', wraplength=1100)
        self.action_text.pack(anchor='w', fill='x', pady=(0, 7))
        table_frame = ttk.Frame(outer); table_frame.pack(fill='both', expand=True)
        columns = ('symbol', 'action', 'requested', 'status', 'effective', 'publication')
        self.table = ttk.Treeview(table_frame, columns=columns, show='headings', selectmode='browse', height=12)
        labels = ('Symbol', 'Action', 'Requested', 'Request status', 'Effective group', 'Publication')
        for name, label in zip(columns, labels):
            self.table.heading(name, text=label); self.table.column(name, width=145, stretch=True)
        scrollbar = ttk.Scrollbar(table_frame, orient='vertical', command=self.table.yview)
        self.table.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        self.table.pack(side='left', fill='both', expand=True)
        self.table.bind('<<TreeviewSelect>>', lambda event: self._details())
        self.detail = ttk.Label(outer, text='Select an action to inspect its durable receipt and outcome.',
                                wraplength=1080, justify='left')
        self.detail.pack(fill='x', pady=9)
        actions = ttk.Frame(outer); actions.pack(fill='x')
        for name, label, callback in [
                ('demote_focus', 'Demote own to Focus', lambda: self.demote('focus')),
                ('demote_uni', 'Demote own to Uni', lambda: self.demote('uni')),
                ('withdraw', 'Withdraw selected own request', self.withdraw),
                ('retry', 'Retry pending receipt', self.retry)]:
            button = ttk.Button(actions, text=label, command=callback); button.pack(side='left', padx=(0, 5))
            self.buttons[name] = button
        limits = ttk.Frame(outer); limits.pack(fill='x', pady=(6,0))
        for name, label, callback in [
                ('limit_focus', 'Limit symbol to Focus', lambda: self.submit('limit', target='focus')),
                ('limit_uni', 'Limit symbol to Uni', lambda: self.submit('limit', target='uni')),
                ('clear_limit', 'Clear selected restriction', self.clear_limit)]:
            button = ttk.Button(limits, text=label, command=callback); button.pack(side='left', padx=(0, 5))
            self.buttons[name] = button
        self.privilege = ttk.Label(outer, text='Limits override source demand; clearing a limit can restore existing demand.', wraplength=1100)
        self.privilege.pack(anchor='w', pady=(8, 3))
        ttk.Label(outer, text='Closing this window stops only the controls. The publisher and collectors are managed separately.').pack(anchor='w')
        ttk.Button(outer, text='Close controls', command=self.close).pack(anchor='e')
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self._enable(False)
        self.root.after(0, self._tick)

    def _enable(self, fresh):
        busy = self.pending_action is not None or self.future is not None and self.operation != 'read'
        state = 'normal' if fresh and not busy else 'disabled'
        for name, button in self.buttons.items():
            permitted = name not in ('limit_focus', 'limit_uni', 'clear_limit') or self.model.controls.allow_restrictions
            desired = state if permitted else 'disabled'
            if self.button_states.get(name) != desired:
                button.configure(state=desired)
                self.button_states[name] = desired

    def _can_submit(self):
        return (not self.closed and self.model.fresh and self.pending_action is None
                and (self.future is None or self.operation == 'read'))

    def _selected(self):
        selected = self.table.selection()
        value = self.last_value or {}
        rows = (value if value.get('fresh') else value.get('last_verified') or {}).get('commands', [])
        return next((r for r in rows if selected and r['command_id'] == selected[0]), None)

    def _details(self):
        row = self._selected()
        if row:
            self.detail.configure(text=f"{row['command_id']} | requested {row['requested_at_utc']}\n{row['detail']}"
                + (f"\nOther sources: {', '.join(row.get('other_sources', []))}" if row.get('other_sources') else '')
                + (f"\nDemotion holds: {row['demotion_holds']}" if row.get('demotion_holds') else ''))

    def _start(self, operation, callback):
        if self.closed:
            return False
        if self.future is not None:
            if operation == 'submit' and self._can_submit():
                # Capture at most one deliberate click during a routine read.
                # Finish and validate that read before dispatching the action.
                self.pending_action = callback
                self._enable(False)
                return True
            return False
        self.operation, self.started = operation, time.monotonic()
        self.future = self.pool.submit(callback)
        self._enable(self.model.fresh if operation == 'read' else False)
        return True

    def submit(self, action, **kwargs):
        if not self._can_submit():
            return
        values = dict(kwargs, symbol=self.symbol.get().strip().upper(), reason=self.reason.get())
        cid = 'manual-'+uuid4().hex
        if self._start('submit', lambda: self.model.submit(action, command_id=cid, **values)):
            self.action_text.configure(text='Submitting '+cid)

    def withdraw(self):
        row = self._selected()
        if not row or not row.get('own_request_id'):
            self.action_text.configure(text='Select one of your promotion requests to withdraw.'); return
        if self._can_submit():
            cid = 'manual-'+uuid4().hex
            reason = self.reason.get()
            self._start('submit', lambda: self.model.submit('withdraw', command_id=cid,
                request_id=row['own_request_id'], reason=reason))

    def demote(self, target):
        row = self._selected()
        if not row or not row.get('own_request_id'):
            self.action_text.configure(text='Select one of your requests to lower its demand.'); return
        if self._can_submit():
            cid, reason = 'manual-'+uuid4().hex, self.reason.get()
            self._start('submit', lambda: self.model.submit('demote', command_id=cid,
                request_id=row['own_request_id'], target=target, reason=reason))

    def clear_limit(self):
        row = self._selected()
        if not row or row['action'] != 'limit':
            self.action_text.configure(text='Select a restriction to clear.'); return
        if self._can_submit():
            cid = 'manual-'+uuid4().hex
            reason = self.reason.get()
            self._start('submit', lambda: self.model.submit('clear_limit', command_id=cid,
                symbol=row['symbol'], request_id=row['command_id'], reason=reason))

    def retry(self):
        row = self._selected()
        if not row or row['status'] != 'REQUESTED':
            self.action_text.configure(text='Select a saved request whose backend receipt is pending.'); return
        if self._can_submit():
            self._start('submit', lambda: self.model.controls.retry(row['command_id']))

    def _apply(self, value):
        self.last_value = value
        view = value if value.get('fresh') else value.get('last_verified') or {}
        self.banner.configure(text=('Verified manual membership' if value.get('fresh') else
            'UNAVAILABLE — showing last verified feedback; controls disabled'),
            foreground='#17653a' if value.get('fresh') else '#a12222')
        self.context.configure(text=f"Session {view.get('session_date', '?')} | Operator {view.get('actor_id', '?')} | "
            f"Effective revision {view.get('effective_revision', '?')} | Verified {view.get('observed_at_utc', '?')}\n"
            'Promotions: verified opening Uni only in this candidate. Other symbols require identity/admission support.')
        rows = view.get('commands', [])
        rendered = [(r['command_id'], (r['symbol'] or '—', r['action'], r['requested_group'] or '—',
            r['status'], r['effective_group'], 'pending' if r['publication_pending'] else 'settled')) for r in rows]
        if rendered != self.last_rows:
            selected, position = self.table.selection(), self.table.yview()[0]
            existing = set(self.table.get_children())
            for cid, values in rendered:
                if cid in existing:
                    self.table.item(cid, values=values); existing.remove(cid)
                else: self.table.insert('', 'end', iid=cid, values=values)
            for cid in existing: self.table.delete(cid)
            for cid in selected:
                if self.table.exists(cid): self.table.selection_set(cid)
            self.table.yview_moveto(position)
            self.last_rows = rendered
        self.privilege.configure(text=('Privileged limits are enabled for this bound operator. They override all source demand.'
            if view.get('allow_restrictions') else 'Privileged restrictions are unavailable for this bound operator.'))
        self._details(); self._enable(bool(value.get('fresh')))

    def _tick(self):
        if self.closed: return
        if self.future is None:
            self._start('read', self.model.refresh)
        elif self.future.done():
            operation, future = self.operation, self.future
            self.future = None
            try:
                value = future.result()
                if operation == 'read':
                    self._apply(value); self.read_count += 1
                else:
                    self.action_text.configure(text='Saved action '+value+'. Feedback will refresh below.')
            except Exception as error:
                self.model.fresh = False
                self.action_text.configure(text='Action/refresh could not be confirmed: '+type(error).__name__+
                    '. Refresh feedback; retry a saved pending receipt with its original ID.')
                self._apply({'fresh': False, 'last_verified': self.model.last_verified})
            if self.pending_action is not None:
                callback, self.pending_action = self.pending_action, None
                if self.model.fresh:
                    self._start('submit', callback)
                    self.root.after(50, self._tick)
                    return
                self.action_text.configure(text='Action was not sent: current membership could not be verified. Refresh, then try again.')
            self.root.after(self.interval_ms if operation == 'read' else 0, self._tick)
            return
        elif time.monotonic()-self.started >= 3:
            self.model.fresh = False
            if self.pending_action is not None:
                self.pending_action = None
                self.action_text.configure(text='Action was not sent: membership refresh is delayed. Wait for verified feedback, then try again.')
            self._apply({'fresh': False, 'last_verified': self.model.last_verified})
        self.root.after(50, self._tick)

    def close(self):
        if not self.closed:
            self.closed = True
            self.pending_action = None
            self.pool.shutdown(wait=False, cancel_futures=True)
            self.root.destroy()

    def run(self):
        self.root.mainloop()
