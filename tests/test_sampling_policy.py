from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mb_watchlist_coordinator.models import IntentType, ProducerIntent
from mb_watchlist_coordinator.sampling_policy import SamplingPolicy
from mb_watchlist_coordinator.sampling_projection import SamplingMembership
from mb_watchlist_coordinator.sampling_request_store import RequestConflictError, SamplingRequestStore
from mb_watchlist_coordinator.session import session_expiration


NOW = datetime(2026, 10, 16, 14, tzinfo=timezone.utc)
SESSION = NOW.date()
BASELINE = SamplingMembership(frozenset({"MSFT", "AAPL", "SPY"}), frozenset({"SPY"}), frozenset())
POLICY = SamplingPolicy("super_user", 60, 120, "immediate_cap")


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "policy.sqlite3"
        self.now = NOW
        self.store = self.reopen()
        self.store.initialize()

    def reopen(self, policy=POLICY):
        return SamplingRequestStore(self.path, session_date=SESSION, baseline=BASELINE,
                                    clock=lambda: self.now, policy=policy)

    def at(self, seconds):
        self.now = NOW + timedelta(seconds=seconds)

    def request(self, owner="manual", request_id="m1", target="hot", symbol="MSFT", **kwargs):
        r = ProducerIntent(request_id, owner, IntentType.ENSURE_PRESENT, frozenset({symbol}), self.now,
            metadata={"session_date": SESSION.isoformat(), "sampling_channel": target})
        return self.store.submit_request(replace(r, **kwargs), actor_id=owner)

    def cancel(self, owner="manual", request_id="m1", command="cancel"):
        return self.store.cancel_request(command, owner_id=owner, request_id=request_id, actor_id=owner)

    def restrict(self, rid="r1", cap="focus", seconds=300, actor="super_user", symbol="MSFT"):
        return self.store.restrict_symbol(rid, symbol=symbol, max_group=cap, actor_id=actor,
            expires_at=NOW + timedelta(seconds=seconds) if seconds is not None else None)

    def clear(self, rid="r1", command="clear", actor="super_user"):
        return self.store.clear_restriction(command, symbol="MSFT", restriction_id=rid, actor_id=actor)

    def state(self):
        return self.store.states()[-1]

    def test_promotion_is_immediate(self):
        self.request()
        self.assertEqual(self.state().applied.hot, {"MSFT"})
        self.assertEqual(self.state().demotion_holds, ())

    def test_residence_and_grace_both_bound_demotion(self):
        self.request(); self.at(10); self.cancel()
        holds = self.state().demotion_holds
        self.assertEqual(datetime.fromisoformat(holds[0]["demotion_at_utc"]), NOW + timedelta(seconds=120))
        self.at(119); self.store.tick("early")
        self.assertEqual(self.state().applied.hot, {"MSFT"})
        self.at(120); self.store.tick("due")
        self.assertEqual(self.state().applied, BASELINE)

    def test_grace_still_applies_after_long_residence(self):
        self.request(); self.at(300); self.cancel()
        self.at(359); self.store.tick("early")
        self.assertEqual(self.state().applied.hot, {"MSFT"})
        self.at(360); self.store.tick("due")
        self.assertEqual(self.state().applied, BASELINE)

    def test_renewed_demand_clears_pending_demotion_and_restarts_grace(self):
        self.request(); self.at(10); self.cancel()
        self.at(100); self.request("halts", "h1")
        self.assertEqual(self.state().demotion_holds, ())
        self.at(110); self.cancel("halts", "h1", "cancel-halt")
        self.at(169); self.store.tick("early")
        self.assertEqual(self.state().applied.hot, {"MSFT"})
        self.at(170); self.store.tick("due")
        self.assertEqual(self.state().applied, BASELINE)

    def test_focus_is_retained_while_hot_has_a_later_deadline(self):
        self.request(target="focus")
        self.at(60); self.request("halts", "h1")
        self.at(61); self.cancel()
        self.at(62); self.cancel("halts", "h1", "h-cancel")
        self.at(122); self.store.tick("focus-due")
        self.assertEqual(self.state().applied.focus, {"SPY", "MSFT"})
        hold = next(h for h in self.state().demotion_holds if h["channel"] == "focus")
        self.assertIn("hot_dependency", hold["held_by"])
        self.at(180); self.store.tick("hot-due")
        self.assertEqual(self.state().applied, BASELINE)

    def test_hot_demotion_keeps_independent_focus_demand(self):
        self.request(target="focus"); self.request("halts", "h1")
        self.at(10); self.cancel("halts", "h1")
        self.at(120); self.store.tick("due")
        self.assertEqual(self.state().applied.hot, set())
        self.assertEqual(self.state().applied.focus, {"MSFT", "SPY"})

    def test_focus_cap_is_immediate_despite_minimum_residence(self):
        self.request(); self.at(1); self.restrict()
        state = self.state()
        self.assertEqual(state.applied.hot, set())
        self.assertEqual(state.applied.focus, {"MSFT", "SPY"})
        self.assertEqual(state.unrestricted_desired.hot, {"MSFT"})
        self.assertEqual(state.reasons_for("MSFT", "hot"), (("manual", "m1"),))

    def test_uni_cap_is_immediate_and_can_bound_baseline_focus(self):
        self.request(); self.at(1); self.restrict(cap="uni")
        self.assertEqual(self.state().applied, BASELINE)
        self.restrict("spy-cap", cap="uni", symbol="SPY")
        self.assertEqual(self.state().applied.focus, set())
        self.assertEqual(self.state().applied.uni, BASELINE.uni)

    def test_ordinary_actor_cannot_set_a_restriction(self):
        self.request()
        result = self.restrict(actor="manual")
        self.assertFalse(result.event.accepted)
        self.assertEqual(result.event.rejection_reason, "not_restriction_authority")
        self.assertEqual(self.state().applied.hot, {"MSFT"})

    def test_ordinary_actor_cannot_clear_a_restriction(self):
        self.request(); self.restrict()
        result = self.clear(actor="manual")
        self.assertFalse(result.event.accepted)
        self.assertEqual(self.state().applied.hot, set())

    def test_new_requests_remain_recorded_but_cannot_bypass_a_cap(self):
        self.restrict(cap="uni"); self.request(); self.request("halts", "h1")
        self.assertEqual(self.state().applied, BASELINE)
        self.assertEqual(len(self.state().active_requests), 2)
        self.clear()
        self.assertEqual(self.state().applied.hot, {"MSFT"})

    def test_replacement_does_not_revive_older_restriction(self):
        self.request(); self.restrict("older", "uni", 300)
        self.at(1); self.restrict("newer", "focus", 50)
        self.assertEqual(self.state().applied.focus, {"MSFT", "SPY"})
        self.at(50); self.store.tick("expiry")
        self.assertEqual(self.state().applied.hot, {"MSFT"})
        self.assertEqual(self.state().active_restrictions, ())

    def test_stale_clear_cannot_remove_replacement(self):
        self.request(); self.restrict("older"); self.restrict("newer", "uni")
        result = self.clear("older")
        self.assertFalse(result.event.accepted)
        self.assertEqual(result.event.rejection_reason, "restriction_not_current")
        self.assertEqual(self.state().active_restrictions[0]["restriction_id"], "newer")

    def test_expiry_rechecks_demand_at_exact_boundary(self):
        self.request(); self.restrict(seconds=50)
        self.at(49); self.store.tick("early")
        self.assertEqual(self.state().applied.hot, set())
        self.at(50); self.store.tick("expiry")
        self.assertEqual(self.state().applied.hot, {"MSFT"})

    def test_clear_does_not_restore_withdrawn_request(self):
        self.request(); self.restrict(cap="uni"); self.cancel(); self.clear()
        self.assertEqual(self.state().applied, BASELINE)

    def test_expiry_does_not_restore_expired_request(self):
        self.request(expires_at=NOW + timedelta(seconds=20)); self.restrict(cap="uni", seconds=50)
        self.at(50); self.store.tick("expiry")
        self.assertEqual(self.state().applied, BASELINE)

    def test_reentry_starts_new_residence_instead_of_reusing_old_timer(self):
        self.request(); self.at(1); self.restrict(cap="uni")
        self.at(100); self.clear(); self.at(101); self.cancel()
        self.at(219); self.store.tick("early")
        self.assertEqual(self.state().applied.hot, {"MSFT"})
        self.at(220); self.store.tick("due")
        self.assertEqual(self.state().applied, BASELINE)

    def test_default_expiry_is_session_end_and_survives_restart(self):
        self.restrict(seconds=None)
        first = self.state().payload()
        expiry = self.state().active_restrictions[0]["expires_at_utc"]
        self.assertEqual(datetime.fromisoformat(expiry), session_expiration(SESSION))
        self.store = self.reopen()
        self.assertEqual(self.state().payload(), first)

    def test_explicit_deadline_cannot_exceed_session_or_be_expired(self):
        result = self.store.restrict_symbol("too-long", symbol="MSFT", max_group="uni", actor_id="super_user",
            expires_at=session_expiration(SESSION) + timedelta(seconds=1))
        self.assertEqual(result.event.rejection_reason, "restriction_exceeds_session")
        result = self.restrict("expired", seconds=0)
        self.assertEqual(result.event.rejection_reason, "restriction_already_expired")

    def test_wrong_policy_cannot_reopen_ledger(self):
        self.request()
        for policy in (None, replace(POLICY, super_user_id="other"), replace(POLICY, demotion_grace_seconds=5)):
            with self.subTest(policy=policy), self.assertRaises(ValueError):
                self.reopen(policy).initialize()
        self.assertEqual(len(self.store.events()), 1)

    def test_unconfigured_legacy_mode_preserves_members_and_forbids_caps(self):
        path = self.path.with_name("legacy.sqlite3")
        legacy = SamplingRequestStore(path, session_date=SESSION, baseline=BASELINE, clock=lambda: self.now)
        legacy.initialize()
        with self.assertRaisesRegex(ValueError, "explicit policy"):
            legacy.restrict_symbol("r1", symbol="MSFT", max_group="uni", actor_id="super_user")
        self.assertEqual(legacy.events(), ())

    def test_ordinary_timers_survive_restart_without_reset(self):
        self.request(); self.at(10); self.cancel()
        first = self.state().payload()
        self.at(50); self.store = self.reopen()
        self.assertEqual(self.state().payload(), first)
        self.at(120); self.store.tick("due")
        self.assertEqual(self.state().applied, BASELINE)

    def test_cap_overrides_pending_ordinary_hold(self):
        self.request(); self.at(1); self.cancel()
        self.at(2); self.restrict(cap="uni")
        self.assertEqual(self.state().applied, BASELINE)
        self.assertEqual(self.state().demotion_holds, ())

    def test_unrelated_symbol_hold_is_not_reset_by_restriction(self):
        self.request(symbol="AAPL"); self.at(1); self.cancel()
        first = next(h["demotion_at_utc"] for h in self.state().demotion_holds if h["channel"] == "hot")
        self.at(10); self.restrict(cap="uni")
        self.assertEqual(next(h["demotion_at_utc"] for h in self.state().demotion_holds if h["channel"] == "hot"), first)

    def test_set_and_clear_retries_keep_original_receipts(self):
        first = self.restrict(seconds=None)
        self.at(10); retry = self.restrict(seconds=None)
        self.assertFalse(retry.inserted)
        self.assertEqual(retry.event, first.event)
        first = self.clear(); retry = self.clear()
        self.assertFalse(retry.inserted)
        self.assertEqual(retry.event, first.event)

    def test_conflicting_restriction_identity_does_not_replace_current(self):
        self.restrict()
        with self.assertRaises(RequestConflictError):
            self.restrict(cap="uni")
        self.assertEqual(self.state().active_restrictions[0]["max_group"], "focus")

    def test_changed_stored_restriction_fails_replay(self):
        self.restrict()
        with closing(sqlite3.connect(self.path)) as connection, connection:
            row = connection.execute("SELECT payload FROM request_event WHERE kind='restrict'").fetchone()
            payload = json.loads(row[0]); payload["max_group"] = "uni"
            connection.execute("UPDATE request_event SET payload=?", (json.dumps(payload),))
        with self.assertRaises(ValueError):
            self.store.states()

    def test_active_restriction_and_holds_are_immutable(self):
        self.request(); self.restrict()
        with self.assertRaises(TypeError):
            self.state().active_restrictions[0]["expires_at_utc"] = "forged"

    def test_future_request_is_not_activated_early_by_clear(self):
        self.request(effective_from=NOW + timedelta(seconds=50)); self.restrict(cap="uni"); self.clear()
        self.assertEqual(self.state().applied, BASELINE)
        self.at(50); self.store.tick("activation")
        self.assertEqual(self.state().applied.hot, {"MSFT"})

    def test_invalid_policy_settings_are_rejected(self):
        for change in ({"super_user_id": ""}, {"restriction_timing": "unspecified"},
                       {"demotion_grace_seconds": -1}, {"minimum_residence_seconds": float("inf")},
                       {"demotion_grace_seconds": True}, {"minimum_residence_seconds": float("nan")}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                replace(POLICY, **change)

    def test_explicit_zero_delays_allow_immediate_ordinary_demotion(self):
        path = self.path.with_name("zero.sqlite3")
        self.store = SamplingRequestStore(path, session_date=SESSION, baseline=BASELINE,
            policy=replace(POLICY, demotion_grace_seconds=0, minimum_residence_seconds=0), clock=lambda: self.now)
        self.store.initialize(); self.request(); self.cancel()
        self.assertEqual(self.state().applied, BASELINE)

    def test_impossible_datetime_deadline_is_rejected_before_ledger_creation(self):
        path = self.path.with_name("invalid.sqlite3")
        with self.assertRaisesRegex(ValueError, "datetime range"):
            SamplingRequestStore(path, session_date=SESSION, baseline=BASELINE,
                policy=replace(POLICY, minimum_residence_seconds=1e13))
        self.assertFalse(path.exists())

    def test_retries_of_old_set_and_clear_do_not_replace_current_restriction(self):
        self.restrict("old"); self.clear("old", command="old-clear")
        self.restrict("current", cap="uni")
        self.assertFalse(self.restrict("old").inserted)
        self.assertFalse(self.clear("old", command="old-clear").inserted)
        self.assertEqual(self.state().active_restrictions[0]["restriction_id"], "current")

    def test_super_user_uses_a_cap_instead_of_erasing_foreign_request(self):
        self.request()
        result = self.store.cancel_request("foreign", owner_id="manual", request_id="m1", actor_id="super_user")
        self.assertFalse(result.event.accepted)
        self.restrict(cap="uni")
        self.assertEqual(self.state().reasons_for("MSFT", "hot"), (("manual", "m1"),))

    def test_live_object_configuration_cannot_change_ledger_authority(self):
        self.store.policy = replace(POLICY, super_user_id="other")
        with self.assertRaisesRegex(ValueError, "configuration changed"):
            self.store.tick("changed-config")
        self.assertEqual(self.reopen().events(), ())
