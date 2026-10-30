"""Display updates and close behavior without requiring a desktop in unit tests."""
from concurrent.futures import Future
from contextlib import redirect_stdout
from io import StringIO
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from mb_watchlist_coordinator.daily_membership_window import MembershipWindow, main
import test_daily_membership_status as fixture


class Label:
    def configure(self, **kwargs):
        if 'text' in kwargs: self.value = kwargs['text']


class Box:
    def __init__(self):
        self.lines, self.selected, self.offset, self.deletions = [], set(), .5, 0
    def yview(self): return self.offset, 1
    def curselection(self): return tuple(sorted(self.selected))
    def get(self, index): return self.lines[index]
    def delete(self, *args):
        self.lines, self.selected = [], set()
        self.deletions += 1
    def insert(self, index, value): self.lines.append(value)
    def selection_set(self, index): self.selected.add(index)
    def size(self): return len(self.lines)
    def yview_moveto(self, value): self.offset = value


class WindowTests(unittest.TestCase):
    def setUp(self):
        self.case = fixture.MembershipStatusTests('test_opening_rosters_are_not_repeated_in_delta_panels')
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.window = object.__new__(MembershipWindow)
        w = self.window
        w.model = self.case.model
        w.labels = {k: Label() for k in ('banner', 'context', 'health', 'collection', 'warning')}
        w.boxes = {k: Box() for k in ('hot', 'focus', 'uni')}
        w.headings = {k: Label() for k in w.boxes}
        w.last_panels, w.last_value = None, None

    def test_completed_membership_refresh_replaces_lists_in_place(self):
        w = self.window
        w._apply(self.case.model.refresh())
        self.case.scene.add()
        w._apply(self.case.model.refresh())
        self.assertIn('NVDA', w.boxes['hot'].lines[0])
        self.assertIn('(1)', w.headings['focus'].value)
        self.assertEqual(len(w.boxes['uni'].lines), 1)

    def test_unchanged_lists_preserve_selection_and_do_not_scroll_or_rewrite(self):
        w = self.window
        self.case.scene.add()
        w._apply(self.case.model.refresh())
        w.boxes['hot'].selected.add(0)
        deletions = w.boxes['hot'].deletions
        w._apply(self.case.model.refresh())
        self.assertEqual(w.boxes['hot'].deletions, deletions)
        self.assertEqual(w.boxes['hot'].selected, {0})
        self.assertEqual(w.boxes['hot'].offset, .5)

    def test_failed_refresh_keeps_the_lists_and_changes_the_visible_banner(self):
        w = self.window
        self.case.scene.add()
        w._apply(self.case.model.refresh())
        (self.case.scene.state_root/'session.json').write_text('{}')
        w._apply(self.case.model.refresh())
        self.assertIn('LAST VERIFIED', w.labels['banner'].value)
        self.assertIn('NVDA', w.boxes['hot'].lines[0])
        self.assertIn('current health unavailable', w.labels['health'].value)

    def test_only_one_read_is_in_flight_so_a_slow_read_cannot_queue_refreshes(self):
        w = self.window
        future = Future()
        submits, callbacks = [], []
        w.pool = SimpleNamespace(submit=lambda fn: submits.append(fn) or future)
        w.root = SimpleNamespace(after=lambda *args: callbacks.append(args))
        w.closed, w.future = False, None
        w.read_started = None
        for _ in range(10):
            w._tick()
        self.assertEqual(len(submits), 1)
        self.assertIs(w.future, future)
        self.assertEqual(len(callbacks), 10)

    def test_unexpected_background_error_is_visible_and_refresh_can_continue(self):
        w = self.window
        w.model.refresh()
        future = Future()
        future.set_exception(RuntimeError('synthetic'))
        w.future, w.closed, w.read_count, w.interval_ms = future, False, 0, 1000
        callbacks = []
        w.root = SimpleNamespace(after=lambda *args: callbacks.append(args))
        w._tick()
        self.assertIn('LAST VERIFIED', w.labels['banner'].value)
        self.assertIsNone(w.future)
        self.assertEqual(callbacks[0][0], 1000)

    def test_close_stops_only_display_executor_and_destroys_its_window(self):
        w = self.window
        events = []
        w.closed = False
        w.pool = SimpleNamespace(shutdown=lambda **kw: events.append(('executor', kw)))
        w.root = SimpleNamespace(destroy=lambda: events.append(('window', 'closed')))
        before = {p: p.read_bytes() for p in self.case.scene.state_root.iterdir() if p.is_file()}
        w.close()
        w.close()
        self.assertEqual(len(events), 2)
        self.assertTrue(w.closed)
        self.assertEqual(before, {p: p.read_bytes() for p in self.case.scene.state_root.iterdir() if p.is_file()})

    def test_one_shot_cli_reads_without_importing_tk_or_constructing_a_window(self):
        with patch('mb_watchlist_coordinator.daily_membership_window.MembershipWindow', side_effect=AssertionError('unexpected GUI')):
            with redirect_stdout(StringIO()) as output:
                code = main(['--state-root', str(self.case.scene.state_root), '--once'])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())['baseline_revision'], 1)


if __name__ == '__main__':
    unittest.main()
