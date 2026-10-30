# Qualify a useful operating envelope without one market day per expansion

The operator's concern is accepted: sparse natural Nasdaq halt traffic is a weak
primary stress test. The one-symbol trial scope was carried into the daily
proposal too conservatively. Do not prescribe successive one-symbol market-day
stages. The current p83 artifact and Windows83/84 acceptance remain unchanged;
its one-symbol proposed production activation is pending revision, not approved.

Choose one practical multi-symbol ceiling with headroom, then qualify the whole
affected envelope together. A quiet real session need not trigger a smaller
rollout stage or another market-day wait. No new ceiling is selected by this
plan, and no unlimited live load or production change is authorized.

## What the inspected source already covers

- test_sampling_requests.py has parallel appenders preserving the command chain.
- test_sampling_admission.py has simultaneous distinct contenders that cannot
  overbook available places, deduplication and retained admission reconstruction.
- test_sampling_service.py covers publication/acknowledgement restart recovery.
- Accepted daily collector/ownership/recovery scopes include duplicate-owner
  rejection and process loss around native acquisition persistence.
- The accepted representative capacity fixture seeds the Uni/Focus background
  and one-symbol Hot history, then executes two actual native tail acquisitions.
  It is not a composed multi-symbol burst or full elapsed-session stress proof.

These are source/evidence observations, not new test executions this turn. Reuse
accepted unchanged scopes; qualify the changed composition and larger workload.

The native acquisition path batches symbols, and daily Hot batch_size is400.
Within one batch a larger Hot roster need not increase requests per scheduled
slot, but does increase response size, observation count and processing/storage
work. Larger admissions also grow Uni/Focus. Review all resulting batch
boundaries and actual timings; request count alone is not a capacity proof.

The operating proposal contains both active-Hot and distinct-admission limits.
daily_session.py also seals an identity quote guard with three permits and one
distinct authorized symbol. A Hot-cap-only edit would therefore be insufficient.
Review identity budgets/dispatch, admission, publication, collection, history,
status and retained-state restart together before selecting the concrete limits.

## Focused market-closed qualification

1. Drive the actual daily composition with synthetic/provider substitutes and
   saved captures, isolated SQLite files and owned processes. Keep synthetic
   material isolated from production journals. Force bursts and repeated or
   overlapping candidate records; do not wait for natural halts.
2. Exercise zero, representative, proposed-limit and over-limit cases in the
   same qualification effort. Include symbols inside/outside opening Uni/Focus,
   and verify nested membership, durable dispositions and visible cap handling.
3. Force relevant interleavings: admission/publication during polling and status
   reads; duplicate delivery; process loss before/after request/publication/
   acquisition commits; resume with preserved identities and charged budgets.
   Use barriers or equivalent coordination where possible instead of relying
   only on random scheduling to reveal races.
4. Run a sustained proposed-limit native acquisition load with realistic quote
   shapes and concurrent Uni/Focus writes. Combine full-size retained history
   with actual elapsed tail/cold-start measurements. Label seeded history and
   elapsed execution distinctly; neither fabricates a full live provider day.
5. Inject bounded latency, busy/read-sharing conflicts and provider-stop faults
   relevant to the larger composition. Retain original deadlines and explicit
   failures; measure latency distributions, growth, gaps, cleanup and restart
   behavior. Do not lengthen watchdogs merely to obtain a passing result.
6. Audit the resulting journals, reconcile each admission/outcome and compare
   fresh replays. Package only affected Windows checks for the revised frozen
   candidate; do not rerun unrelated accepted live/GUI/recovery tests unchanged.

## Live observation has a different role

After the revised candidate/settings are reviewable and approved, observe one
useful controlled production envelope. Live evidence assesses actual source and
broker behavior, the workstation and session longevity. Off-hours bounded
broker batching/timing can supply additional provider evidence when necessary;
it does not require a qualifying natural halt or prove market-open performance.
Retain honest live-coverage limits when natural events are sparse.

Synthetic stress and forced interleavings improve repeatability but cannot
prove every race or real-provider load behavior. A quiet production day is
valid observation with limited natural-event coverage, not proof that maximum
load occurred. Capacity increases should follow measured envelope results or
actual findings, not an automatic one-day-per-increase rule.

Friday production closeout/Monday preparation remain separate ordinary work.
Monday is a target contingent on focused revision/qualification and activation
approval; no additional sequence of market-day gates is introduced by this plan.
