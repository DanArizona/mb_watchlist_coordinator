from datetime import date, datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from mb_watchlist_coordinator.operating_plan import build_plan, main, proposed_policy, validate_policy
from mb_watchlist_coordinator.sampling_requests import digest


class OperatingPlanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.opening = self.root/"r0.json"; self.focus = self.root/"r1.json"
        common = {"session_date": "2026-10-28", "effective_at": "2026-10-28T09:30:00-04:00",
                  "uni_symbols": ["CLRO", "TEST"], "hot_symbols": [], "source": "synthetic operating plan"}
        self.opening.write_text(json.dumps(dict(common, revision=0, focus_symbols=[])))
        self.focus.write_text(json.dumps(dict(common, revision=1, focus_symbols=["CLRO"])))
        self.ecfg = self.root/"never-open-this-configuration.ecfg"

    def plan(self):
        return build_plan(self.opening, self.focus, market_data_root=self.root, ecfg_path=self.ecfg)

    def test_plan_binds_proposals_and_generates_three_independent_windows(self):
        value = self.plan(); content = dict(value); checksum = content.pop("plan_sha256")
        self.assertEqual(digest(content), checksum)
        self.assertEqual(value["opening_counts"], {"uni": 2, "focus": 1, "hot": 0})
        self.assertEqual(value["cadence_seconds"]["focus"], [10, 20, 40, 50])
        self.assertEqual(value["expected_full_session_slots"], {"uni": 780, "focus": 1560, "future_hot": 9360})
        self.assertEqual(len(value["independent_windows"]), 3)
        for channel in ("uni", "focus", "health"):
            self.assertIn("--cadence-profile", value["commands"][channel])
        self.assertIn("--supervise", value["commands"]["health"])
        self.assertFalse(value["future_hot_driver"]["activation_allowed"])
        self.assertIsNone(value["future_hot_driver"]["launch_command"])
        self.assertFalse(self.ecfg.exists())
        self.assertFalse((self.root/"output").exists())

    def test_proposed_daily_limits_are_never_the_live_profile_caps(self):
        value = self.plan()
        self.assertEqual(value["policy"]["limits"]["maximum_hot_quote_calls"], 9360)
        self.assertEqual(value["policy"]["limits"]["maximum_active_hot_symbols"], 1)
        self.assertEqual(value["policy"]["status"], "PROPOSED_NOT_ADOPTED")
        self.assertFalse(value["policy"]["hot_enabled"])

    def test_policy_edits_cannot_enable_hot_or_relax_the_review_candidate(self):
        for key, value in (("hot_enabled", True), ("cadence_profile", "legacy-v1")):
            policy = proposed_policy(); policy[key] = value
            with self.assertRaises(ValueError): validate_policy(policy)
        policy = proposed_policy(); policy["limits"]["maximum_active_hot_symbols"] = True
        with self.assertRaises(ValueError): validate_policy(policy)

    def test_mismatched_dates_revisions_or_universe_are_refused(self):
        original = json.loads(self.focus.read_text())
        for key, value in (("session_date", "2026-10-29"), ("revision", 2),
                           ("uni_symbols", ["CLRO"]), ("hot_symbols", ["CLRO"])):
            self.focus.write_text(json.dumps(dict(original, **{key: value})))
            with self.assertRaises(ValueError): self.plan()
        self.focus.write_text(json.dumps(original))

    def test_no_authentication_or_network_is_used_to_build_a_plan(self):
        import socket
        with patch.object(socket, "socket", side_effect=AssertionError("Network forbidden")):
            self.assertEqual(self.plan()["status"], "REVIEW_CANDIDATE_HOT_DISABLED")

    def test_main_writes_only_an_explicit_new_plan_directory(self):
        from contextlib import redirect_stdout
        from io import StringIO
        output = self.root/"plans"/"first"
        args = [str(self.opening), str(self.focus), "--market-data-root", str(self.root),
                "--ecfg", str(self.ecfg), "--output-dir", str(output)]
        with redirect_stdout(StringIO()):
            self.assertEqual(main(args), 0)
            self.assertEqual(main(args), 2)
        self.assertTrue((output/"operating-plan.json").is_file())
        self.assertFalse(self.ecfg.exists())


if __name__ == "__main__": unittest.main()
