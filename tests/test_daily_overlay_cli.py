import argparse
from contextlib import redirect_stdout,redirect_stderr
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch,Mock
import test_daily_overlay as fixtures
from mb_watchlist_coordinator.daily_overlay_cli import main,reader_from_arguments,serve
from mb_watchlist_coordinator.daily_overlay import DailyOverlayModel


class DailyOverlayCLITests(unittest.TestCase):
    def setUp(self):
        self.case=fixtures.DailyOverlayTests();self.case.setUp();self.addCleanup(self.case.doCleanups)

    def test_one_shot_snapshot_does_not_construct_a_browser_or_server(self):
        out=io.StringIO()
        with (patch('mb_watchlist_coordinator.daily_overlay_cli.serve',side_effect=AssertionError('no server')),
                patch('webbrowser.open',side_effect=AssertionError('no browser')),redirect_stdout(out)):
            # Actual wall clock is earlier than this trusted fixture's future
            # session; the no-state-creation boundary remains observable.
            code=main(['snapshot','--state-root',str(self.case.scene.state_root),'--symbol','IBM'])
        self.assertIn(code,(0,1));self.assertIn('fresh',json.loads(out.getvalue()))

    def test_missing_state_snapshot_returns_unavailable_without_creating_files(self):
        root=self.case.scene.root/'absent';out=io.StringIO()
        with redirect_stdout(out):code=main(['snapshot','--state-root',str(root)])
        self.assertEqual(code,1);self.assertIsNone(json.loads(out.getvalue())['snapshot']);self.assertFalse(root.exists())

    def test_only_read_verbs_are_accepted_before_any_password_or_owner(self):
        with patch('getpass.getpass',side_effect=AssertionError('no credentials')),redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):main(['start','--state-root',str(self.case.scene.state_root)])

    def test_generated_summary_routes_to_its_original_state_and_journal(self):
        scene=self.case.scene;path=scene.root/'operating-summary.json'
        path.write_text(json.dumps({'contract':'daily-hot-operator-delivery-v1','result':'PREPARED_NOT_ACTIVATED',
            'state_root':str(scene.state_root),'journal_path':str(scene.journal)}))
        r=reader_from_arguments(argparse.Namespace(operating_summary=str(path),candle_directory=None,state_root=None))
        r.clock=lambda:scene.now;r.membership_reader.clock=r.clock
        self.assertEqual(r.snapshot('NVDA').overlay.symbol,'NVDA')

    def test_summary_journal_rebinding_is_refused(self):
        scene=self.case.scene;path=scene.root/'operating-summary.json'
        path.write_text(json.dumps({'contract':'daily-hot-operator-delivery-v1','result':'PREPARED_NOT_ACTIVATED',
            'state_root':str(scene.state_root),'journal_path':str(scene.root/'other.sqlite3')}))
        r=reader_from_arguments(argparse.Namespace(operating_summary=str(path),candle_directory=None,state_root=None))
        r.clock=lambda:scene.now;r.membership_reader.clock=r.clock
        self.assertFalse(DailyOverlayModel(r).refresh('NVDA').fresh)

    def test_viewer_is_loopback_only_and_stops_only_its_wsgi_server(self):
        fake=Mock();fake.bound_port=12345
        with (patch('mb_market_data.local_dashboard_server.LocalDashboardServer',return_value=fake) as server,
                patch('webbrowser.open') as browser,redirect_stdout(io.StringIO())):
            serve(self.case.model,symbol='NVDA',port=0)
        self.assertEqual(server.call_args.kwargs['host'],'127.0.0.1')
        fake.serve_until_stopped.assert_called_once();browser.assert_called_once_with('http://127.0.0.1:12345')

    def test_no_browser_option_keeps_viewer_start_independent_of_browser_launch(self):
        fake=Mock();fake.bound_port=12345
        with (patch('mb_market_data.local_dashboard_server.LocalDashboardServer',return_value=fake),
                patch('webbrowser.open',side_effect=AssertionError('no browser')),redirect_stdout(io.StringIO())):
            serve(self.case.model,symbol='NVDA',open_browser=False)
        fake.serve_until_stopped.assert_called_once()


if __name__=='__main__':unittest.main()
