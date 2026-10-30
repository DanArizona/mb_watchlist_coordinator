"""Persistent, read-only membership window. Closing it stops only this display."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import sys
import time

from .daily_membership_status import MembershipDisplayModel, MembershipStatusReader, display_lines, GROUPS


class MembershipWindow:
    def __init__(self, model, *, title='MasterBot membership status', interval_ms=1000):
        import tkinter as tk
        from tkinter import ttk
        self.root = tk.Tk()
        self.root.title(title)
        self.root.geometry('1040x490')
        self.root.minsize(760, 370)
        self.model, self.interval_ms = model, interval_ms
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='membership-read')
        self.future = None
        self.read_started = None
        self.closed = False
        self.read_count = 0
        self.last_value = None
        self.last_panels = None
        self.labels = {}
        outer = ttk.Frame(self.root, padding=14)
        outer.pack(fill='both', expand=True)
        for name in ('banner', 'context', 'health', 'collection', 'warning'):
            font = ('Segoe UI', 12, 'bold') if name == 'banner' else ('Segoe UI', 10)
            label = ttk.Label(outer, text='Reading saved membership...', font=font, wraplength=970)
            label.pack(anchor='w', fill='x', pady=(0, 5))
            self.labels[name] = label
        columns = ttk.Frame(outer)
        columns.pack(fill='both', expand=True, pady=(8, 10))
        self.boxes, self.headings = {}, {}
        for index, channel in enumerate(GROUPS):
            columns.columnconfigure(index, weight=1, uniform='membership')
            panel = ttk.Frame(columns, padding=(0, 0, 10 if index < 2 else 0, 0))
            panel.grid(row=0, column=index, sticky='nsew')
            heading = ttk.Label(panel, text=channel.upper(), font=('Segoe UI', 11, 'bold'))
            heading.pack(anchor='w')
            ttk.Label(panel, text='Symbol      first effective time (ET)', font=('Segoe UI', 9)).pack(anchor='w', pady=(2, 4))
            container = ttk.Frame(panel)
            container.pack(fill='both', expand=True)
            box = tk.Listbox(container, font=('Consolas', 11), activestyle='none',
                             exportselection=False, height=9)
            scroll = ttk.Scrollbar(container, orient='vertical', command=box.yview)
            box.configure(yscrollcommand=scroll.set)
            scroll.pack(side='right', fill='y')
            box.pack(side='left', fill='both', expand=True)
            self.boxes[channel], self.headings[channel] = box, heading
        columns.rowconfigure(0, weight=1)
        footer = ttk.Frame(outer)
        footer.pack(fill='x')
        ttk.Label(footer, text='Read-only. No API requests. Close this window or press Q to stop only the display.').pack(side='left')
        ttk.Button(footer, text='Close display', command=self.close).pack(side='right')
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.root.bind('<q>', lambda event: self.close())
        self.root.bind('<Q>', lambda event: self.close())
        self.root.after(0, self._tick)

    def _apply(self, value):
        self.last_value = value
        view = display_lines(value)
        for name, label in self.labels.items():
            label.configure(text=view[name])
        self.labels['banner'].configure(foreground='#17653a' if value.get('fresh') else '#a12222')
        state = (value if value.get('fresh') else value.get('last_verified') or {}).get('controller', {}).get('state')
        self.labels['health'].configure(foreground='#a12222' if state in ('STALE', 'BLOCKED', 'UNAVAILABLE') else '#202020')
        # Repeated refreshes preserve list selection and scroll position.
        if view['panels'] != self.last_panels:
            for channel, box in self.boxes.items():
                position = box.yview()[0]
                selected = tuple(box.get(i) for i in box.curselection())
                box.delete(0, 'end')
                for line in view['panels'][channel]:
                    box.insert('end', line)
                    if line in selected:
                        box.selection_set(box.size()-1)
                box.yview_moveto(position)
            self.last_panels = view['panels']
        for channel, label in self.headings.items():
            name = 'HOT - all current' if channel == 'hot' else channel.upper()+' - added since r1'
            label.configure(text=name+f" ({view['counts'][channel]})")

    def _tick(self):
        if self.closed:
            return
        if self.future is None:
            self.read_started = time.monotonic()
            self.future = self.pool.submit(self.model.refresh)
        elif self.future.done():
            try:
                value = self.future.result()
            except Exception as error:
                value = {'fresh': False, 'error': type(error).__name__,
                         'last_verified': self.model.last_verified}
            self._apply(value)
            self.read_count += 1
            self.future = None
            self.root.after(self.interval_ms, self._tick)
            return
        elif self.read_started is not None and time.monotonic()-self.read_started >= 3:
            self._apply({'fresh': False, 'error': 'RefreshDelayed',
                         'last_verified': self.model.last_verified})
        self.root.after(50, self._tick)

    def close(self):
        if not self.closed:
            self.closed = True
            self.pool.shutdown(wait=False, cancel_futures=True)
            self.root.destroy()

    def run(self):
        self.root.mainloop()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-root', required=True)
    parser.add_argument('--once', action='store_true', help='Print one read-only snapshot instead of opening a window')
    args = parser.parse_args(argv)
    model = MembershipDisplayModel(MembershipStatusReader(args.state_root))
    if args.once:
        value = model.refresh()
        print(json.dumps(value, indent=2))
        return 0 if value['fresh'] else 1
    window = MembershipWindow(model)
    window.run()
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        print('Membership display could not start:', type(error).__name__, file=sys.stderr)
        raise SystemExit(1)
