# Integrated Hot reliability candidate — November 2, 2026

**Status: SOURCE CANDIDATE ONLY / TEST EXECUTION PENDING / NOT APPROVED FOR WINDOWS OR PRODUCTION.**

This manifest documents a cross-repository experimental source correction. It does not constitute a bundled release, offline PASS, Windows qualification, provider qualification, or any change to the blocked production p85 instance.

## Source refs

- Coordinator branch: `DanArizona/mb_watchlist_coordinator:experiment/hot-slot-reliability-20261102` (contains previously published immutable source-prefix optimization plus new source changes and two focused native integration test cases).
- Native branch: `DanArizona/mb_market_data:experiment/hot-native-deadline-20261102`, derived from remotely accessible `experiment/daily-hot-multi-capacity-20261030`. Latest native edit `53fc9d62155063b3ae2bc5f0bacfd604866241e0`.
- **Provenance gate RESOLVED (2026-11-03):** the earlier chat inspected clean local commit `d37d2c37e3ac9cc2c860d0a2313a1526e30fd23e` and reported an empty complete tree diff against published commit `37c22983bc92055dd322085f191b054921d896d2`. Both have Git tree `38e33f634de94693b7b67b89d15418df82cd4d73` with 151 tracked entries. The GitHub connector independently verified the published commit tree and confirmed that `53fc9d62155063b3ae2bc5f0bacfd604866241e0` descends from `37c2298` with seven commits across four files. Source-baseline equivalence accepted; changes themselves are untested.

## Implemented (not executed)

1. `schwab_quotes.fetch_quotes_batched` passes through only typed `PreProviderDeadlineExpired`; ordinary provider exceptions still normalize to request_error.
2. Coordinator `DailyHotCollector.quotes` preserves the original 750ms check; fatal budget/roster/fields/window violations still set `refused_call`, whereas a verified local deadline crossing raises the typed exception before any provider call.
3. **Both** the generic and daily-specific native acquisition paths now handle typed local deadline as a durable `abandoned` event tied to an already persisted dispatch; no quote acquisition or invented request_error results.
4. Native `record_prior_cycle_overruns` appends exact slot-ID `missed` outcomes without quote calls or empty-membership skips. Coordinator future-only selection records every elapsed next-slot ID before moving to its next future slot. The native audit still recognizes these slots as absent acquisitions; ledger explanations do not change FAIL to PASS.
5. Durable `acknowledged` events may include named phase timings; daily native cycle persists source/verification, state preparation and spool/check phase durations. The final deadline's `abandoned` event also retains callback elapsed and phase timings.
6. Outer shutdown now classifies fresh STOPPING/BLOCKED separately from heartbeat age; three-second freshness unchanged.

## New tests committed but **not yet run**

- Coordinator `tests/test_daily_collector.py`: final local gate crossing after 751ms must become an abandoned missing slot, no quote/provider response and no permanent block; future valid slot may still be collected. A three-second synthetic response-tail overrun must record an explicit missing slot, without catch-up.
- Coordinator `tests/test_daily_operating.py`: RUNNING/STOPPING/BLOCKED/future/stale heartbeat classification.
- Native `tests/test_schwab_quotes.py`: typed local deadline propagates without per-symbol request errors; ordinary provider exception remains request_error.
- Must additionally test: real roster and call budget violations still BLOCK; operating-window violation still BLOCK; restart/replay integrity after newly persisted abandoned and missed events; long retained-history startup and repeated forced bursts; provider-start count exactly zero in the final deadline refusal case; no duplicate finished slot and unchanged generation/identity fences.

## Qualification gates

1. **COMPLETE:** Exact accepted native baseline tree confirmed through clean local comparison and GitHub verification; historical acceptance evidence retained unchanged.
2. Run targeted offline native and Coordinator tests with both source checkouts in a compatible Python environment. Record true results and source fingerprints.
3. Run bounded forced bursts and synthetic retained-history (including Windows scheduler-overrun conditions) without changing real provider budgets or cadence.
4. Build a *single* exact Windows qualification artifact with source inventory and SHA-256. Run its offline verification on MasterBot without touching installed p85.
5. Only after source verification and Windows evidence, prepare explicit changed-production approval. Keep p85 blocked and original November 2 FAIL, 28 pre-stop gaps and 7,292 full-session missing Hot slots intact.

No modifications to main, frozen p85, credentials, provider requests, manual activation or read-only Overlay are part of these source commits. Suppress Automatic Hot remains deferred; ordinary demote remains agreed policy.
