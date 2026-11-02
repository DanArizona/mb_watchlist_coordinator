# November 2 Hot reliability — native correction boundary

Status: DESIGN / SOURCE INSPECTION ONLY. No runtime correction or Windows qualification is claimed.

Baseline: Coordinator experiment/hot-slot-reliability-20261102 at f6c7d596a7760de5d793b0c914001f8b319a79be, original file tree 006200872c5aa0e51070c4c54be325a8c0a51190. Native backend accepted separately at d37d2c37e3ac9cc2c860d0a2313a1526e30fd23e.

## Verified code paths

- src/mb_watchlist_coordinator/daily_collector.py:150-194: quotes() reads native durable dispatch. Lines 165-170 conflate call budget, roster, fields, operating window and 750ms elapsed gate, set refused_call=True and raise a ValueError. Lines 180-183 latch refused_call for expiration after client preparation. Lines 211-215 tick() converts refused_call to a blocked status, otherwise chooses next_slot(... after=max(slot.scheduled_at,clock())).
- src/mb_watchlist_coordinator/daily_operating.py:151-158: _driver_fresh() requires both RUNNING and an age <3s; lines 190-191 label false as controller_progress_stale. A fresh STOPPING state is therefore mislabeled stale.
- Original 28 missing slots: 18 before-dispatch misses, 4 after-dispatch abandonments and 6 preceding-cycle overruns that future-only selection did not record. No missing quote should be reconstructed.

## Required correction contract

1. Separate a *pre-provider dispatch deadline expiration* from genuine fatal roster, symbol-count, call-budget, window, ownership, provider-stop and credential fences. Retain the original .750s limit. The deadline branch must never issue a Schwab quote call.
2. Handle final deadline expiration in the native slot state machine, with a durable typed non-quote outcome tied to the actual configured slot. Do not merely stop setting refused_call in Coordinator: native normalizer currently turns callback exceptions into request_error observations and the final deadline needs native differentiation. Ensure no fabricated acquisition or quote observation. Preserve exact-once append/replay properties.
3. Record skipped configured slots when a preceding collector cycle overruns and future-only next_slot selection advances. Persist reason and phase timing (wake, source/publication checks, dispatch, callback, provider start/end, journal write, acknowledgement where available). Never reclassify real gaps as empty-membership skips or hide them from native coverage audit.
4. Separate heartbeat *age*, *state*, and *terminal reason*. A fresh STOPPING/BLOCKED snapshot is not stale; terminal shutdown is still a valid stop. Preserve generation/binding/fencing checks and unchanged 3s freshness bound.
5. Verify using existing exact 748.125ms -> 751.125ms logical clock reproduction plus four previously accepted refusal cases, two scheduler repro cases, burst and retained history tests. Prove budget/roster/window violations remain fatal. Preserve p85 FAILED evidence and all 28 gaps.

## Integration and qualification order

- Implement native backend correction in a separate experiment branch based on accepted d37d2c37; do not modify frozen p85.
- Integrate Coordinator deadline distinction, future-only skip recording and shutdown classifier against exact native API; add focused regression tests including halt/manual interplay only within already accepted scope.
- Validate locally first, then build one exact Windows candidate for MasterBot. Qualification must explicitly report skipped-slot ledger and audit behavior, startup/cold-reader performance and native/outer outcome consistency.
- No production activation, state unblock, credential prompting, new provider use, changed main branch or claim of PASS before Windows evidence.

Ordinary manual demotion remains the scoped accepted behavior; a later distinct qualifying halt may readmit a symbol subject to normal policy. Suppress Automatic Hot remains deferred.
