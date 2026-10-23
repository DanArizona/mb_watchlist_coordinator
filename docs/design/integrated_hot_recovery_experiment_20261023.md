# Bounded Nasdaq, Coordinator and authenticated Hot recovery experiment

Version 1 — October 23, 2026. **Commands 41/42 Windows-accepted; command 43 catalog-bound startup locally qualified, Windows pending; runtime supervision and full manual resume next.** This document defines the isolated integration increment. It is not an executable live procedure or a live-run result. The limits are also recorded in [contract.json](../../experiments/integrated_hot_recovery_20261023/contract.json).

## 1. Outcome and accepted starting point

Demonstrate this complete path using the actual installed Windows client: retained current/dated Nasdaq evidence → common event/request delivery → ordinary Coordinator admission/publication → authenticated native Hot acquisitions → owned-worker interruption and future-only recovery. Keep original event times, knowledge times and gaps distinguishable.

Reuse the command-32 request reuse, command-33 shared recovery delivery, command-35 paced transport/authority, command-37 native collector, command-38 private credential handoff, and commands-39/40 installed-client evidence. The current implementation/acceptance reference is Coordinator `1a405393798c7311217316993d05d2c1552056d3`, tree `bfe163095f7703f993cbe3e0b9b511817623f502`. The installed helper reference remains mb_tools `abdceb1be988b7ee893b0bed725b90454ddf4f71`. No unchanged earlier qualification is requested.

Production remains independent. The operator supplies read-only opening r0 and Focus r1 proposals. A new, marked experimental schema-v2 journal starts from those verified memberships with **empty Hot**. No experimental Uni/Focus collector runs. Production Hot stays disabled; no main merge, production configuration change or production process control is part of this definition. Normal SDK refresh may update the existing shared token database, as in the accepted probes; that is an explicit shared dependency, not an isolated-token-database claim.

## 2. Two separately invoked live profiles

Each profile has a fresh experimental identity, explicit consent through its own future launcher, its own one-symbol/call budget and one hidden password prompt. There is no automatic second trial or automatic widening of a stopped window.

| Profile | Required demonstration | Goal-based normal stop |
| --- | --- | --- |
| A: ordinary integration | Declared same-day feed scope reconciled, effective Hot membership, actual native quotes and continuous owned-worker operation | 30 completed native Hot acquisitions after a valid post-history CURRENT cutover, with final evidence checks passing |
| B: owned Hot-worker recovery | The same chain, followed by one controlled interruption of the exact owned Hot child | 12 completed Hot acquisitions before the fault, 15 seconds with no replacement child, then 24 completed Hot acquisitions after verified replacement startup |

The selected transition may come from a genuinely new post-baseline live halt or from explicitly recovered earlier same-day evidence. Report `LIVE_NEW` and `RECOVERED_SAME_DAY` separately. A recovered or baseline event never becomes a new-live-halt claim. An already-resumed same-day halt remains eligible only under the existing positive-original-reason and until-close request policy. A missing selected transition leaves the acquisition/recovery demonstration unproved.

First qualify full-controller crash/reopen and human-prompted resume offline as well. Profile B proves the owned Hot-worker live boundary; it does not prove unattended controller or machine restart. A later live controller-restart drill needs its own bounded procedure and evidence.

## 3. Fixed limits per profile

All session boundaries are America/New_York, with aware UTC retained in artifacts. The operator must have current production health before launching live work. An invocation is refused if its complete frozen window cannot fit before 16:00 ET.

| Item | Limit |
| --- | --- |
| Prompt and preflight | Dependency/public-input checks precede the hidden prompt. After submission, bootstrap is bounded at 60 seconds. Human time at the prompt is outside that timer. |
| Frozen acquisition window | Set T0 to the whole-second ceiling of password submission time + 60 seconds (a lead of at least 60 and less than 61 seconds); Tstop = T0 + 720 seconds. Bootstrap must finish before T0. T0 must be at/after 09:30 ET and Tstop at/before 16:00 ET. |
| Active controller | At most 720 seconds from T0; stop earlier when the profile goal is complete or a terminal condition occurs. An independent deadline also bounds blocked child work. |
| Hot membership | At most one distinct admitted symbol over the entire profile, including restarts. Other captured facts retain their normal recorded dispositions. |
| Hot cadence | `:02/:04/:06/:08`, then the same pattern within each ten-second block; all even seconds except multiples of ten. This is 24 opportunities/minute, with 2s/4s gaps. |
| Hot dispatch | Maximum 750ms lateness; one-symbol roster; one batch; fields=all; request timeout 3 seconds; future slots only. |
| Native Hot quote permits | 60 maximum, cumulative across generations and manual resume. Reserved/uncertain dispatches consume budget. Empty-membership slots make no quote call. |
| Identity-resolution permits | 3 maximum one-symbol quote-client calls, including failures/unknown outcomes. Exact symbol identity is required. |
| Total quote-client permits | 63 maximum: 60 Hot + 3 identity resolution. No SPY startup quote and no experimental Uni/Focus quotes are added. SDK authentication/refresh HTTP is separate and must not be counted as zero. |
| Symbol-directory retrieval | At most two bounded source-file retrievals for the reviewed exact-symbol catalog path, 10 seconds each within bootstrap. Preserve source identity/hash and freshness. No silent retries or fallback catalog. |
| Nasdaq feed | At most 10 current/dated attempts combined; at least 60 seconds after each completed attempt, including failures; maximum 10 seconds per attempt and 720-second feed budget. |
| Feed unavailable stop | Three consecutive unavailable attempts, terminal classification, unknown unowned attempt or exhausted bounds stops further feed work with an explicit retained reason. |
| Hot worker generations | At most 3 total starts, including the initial child. Profile B injects exactly one interruption; further failures remain diagnostic and cannot reset budgets. |
| Existing worker health gates | Retain 3-second supervised startup and 3-second heartbeat staleness. The credential entry's separate maximum is 8 seconds; it does not extend the supervisor gate. Earlier limits win. |
| Shutdown and reporting | Exact owned-child cleanup at most 10 seconds; local final audit/replay/reporting at most 60 further seconds. Report unfinished cleanup/reporting explicitly. |

These are maximum bounds, not promised durations or full-window acquisition counts. With 24 Hot slots/minute the 12-minute window contains 288 opportunities; the stricter 60-permit cap and goal-based early stop deliberately constrain this proof. Closing the profile does not backdate a request cancellation or fabricate membership expiry; its until-close demand can remain recorded while the experimental collector is stopped.

## 4. Startup and durable-state ordering

1. Validate proposal date/hash/hierarchy nesting, initial empty Hot, explicit experimental paths and source/dependency inventory. Refuse production-style journal paths, changed dependencies and mixed identities before credential access. Choose the public frozen window before authentication; no window is extended during recovery.
2. Prompt once, retain the manual-session password only in RAM and use the accepted private anonymous-pipe handoff. No password/config contents/token values may enter argv, environment, files, reports or SDK output. A fresh controller needs another human prompt.
3. Accept encrypted configuration and fresh pre/post-client refresh horizons through Tstop plus the accepted 75m30s margin. Interactive reauthorization, missing configuration or late authentication fails closed. Prove this before initializing durable service/journal state or registering the first native `poll_run`; a redacted startup-failure receipt is permitted.
4. Acquire and bind the reviewed catalog, finish bounded bootstrap, then create the fresh isolated journal and its producer/recovery/request/publication/acquisition identities. Source identity and lookup budgets are durable. A missing/corrupt ledger on resume is BLOCKED, not a fresh empty experiment.
5. Initialize the native collector only after authenticated bootstrap. Command 41 closes the initial parent-created journal/`poll_run` ordering gap that remained after command 38. Command 43 extends the ordering to the newly acquired catalog and identity gate; its Windows acceptance remains pending. Running collector supervision still requires coupled qualification before a live launcher is delivered.
6. Start only an explicitly bound authenticated Hot worker under the existing role lease/generation fence. Steady-state heartbeat progress must follow completed work; merely surviving or waiting for a password is not a healthy acquisition heartbeat.

The existing 3s worker startup and 8s credential maximum overlap. An integration timing failure is retained. Do not increase the 3s gate silently; separate non-secret startup progress or another protocol change requires explicit implementation, qualification and a recorded rationale before any later contract revision.

## 5. Feed discovery, recovery and request delivery

Use one scheduler and the existing external-observation/common-outbox path. Establish a valid CURRENT baseline; its existing rows remain baseline evidence. Query exactly the target session's combined halt-date/resumption-date union. Once that explicit dated query is complete, deliver recovered candidates through the ordinary path and obtain a subsequent valid CURRENT cutover before declaring discovery reconciled.

No automatic previous-day queries or renewal of prior-day demand is included. Record `carryover_history_verified=false` and the unknown-carryover limitation for a fresh late start. Preserve off-date/unresolved rows as context. Original LUDP/M reason evidence is required; a later release-only row does not prove the original reason. Every changed halt/resumption observation, source hash and receipt/query provenance remains retained, including facts that do not change membership.

Keep the original event ID and shared source ownership across live/recovered delivery. Reuse only accepted same-source demand covering the remaining until-close window. An exact retry obtains its original disposition. Normal catalog, restriction, lifetime, capacity and outside-Uni admission rules remain authoritative. Once a symbol is admitted, a durable one-symbol fence prevents substitution after a restart or a later request-state change.

The Coordinator publishes the complete nested hierarchy, with the existing 1-second cycle and 0.5-second publication lead/deadline policy. No membership is backdated to the halt time. Hot collection can begin on the first permitted future slot after effective membership; a two-second response is an observation to measure, not a promise. Do not infer release from elapsed halt duration.

Retain raw feed bytes and HTTP diagnostics. HTML/non-feed responses are unavailable evidence, never an empty no-halt result. A valid empty response describes only its returned scope. Feed failure must preserve verified saved demand; it does not by itself authorize killing a healthy owned collector. The separate profile deadline still stops all owned work.

## 6. Interruption, resume and slot accounting

For profile B, trigger only after a fully committed acquisition and its local acknowledgement. Record the selected generation, last confirmed slot, fault request/exit times and exact owned handle. Stop/terminate only that child, hold replacement for 15 seconds, then permit the existing authority to validate/reopen and start a replacement. Do not interrupt a production process or discover ownership from a process-name search.

The recovery path verifies all original identities/prefixes; completes request delivery and journal publication acknowledgements idempotently; recovers saved assembled quote evidence without a provider call; retains an ambiguous dispatch as unknown and charged; and resumes at strictly future slots. No historical quote request fills the deliberate pause. A fresh controller resume is explicit, uses the same frozen Tstop/budgets and requires the human prompt; no automatic new trial window is created.

Record a coverage endpoint at the controller's explicit acquisition-stop request. Native audit must state that `audited_at` value, retain its raw verdict and list exact missing slots. Goal-based early completion must not be audited as if collection were promised to the future Tstop. Profile B's intentional pause/restart slots are reported as real missing coverage, matched to retained fault/ready receipts; they are not empty skips, valid acquisitions or a raw zero-gap audit PASS. Every other unexplained missing/duplicate slot fails the relevant profile. Two fresh native replays must agree over the same retained event sequence.

If a feed/call/time bound stops a run before its goal, preserve the source's INCOMPLETE/stop-required result and mark the unfinished proof explicitly. Do not convert budget exhaustion into an unqualified PASS or reset a durable budget to complete the target count.

## 7. Evidence and verdicts

Each report includes public configuration/source pins, initial hierarchy hashes, all attempt/dispatch counters, selected symbol and transition origin, source event/update/knowledge times, resolver/request/publication/effective timestamps, scheduled/dispatch/response/journal-commit-observed times, worker ownership/generations/exit evidence, missing/unknown slots, remaining scopes and actual CMD prompt return. Commit-observation times are observer receipts, not fabricated database-internal commit timestamps.

Report dimensions separately: discovery reconciliation and its gaps; request/publication correctness; authenticated provider outcomes; native coverage; and recovery demonstration. Native raw audit/replay verdicts are retained. A valid provider response with an old trade time during a halt is not by itself a failed acquisition; invalid/missing/error outcomes retain their real statuses and cannot be relabeled as successful quotes.

| Result | Meaning |
| --- | --- |
| PASS | All applicable profile goals and integrity/budget/ownership checks pass within their bounds, with no unexplained coverage/identity error. Profile B still names its deliberate missing coverage. |
| PASS_WITH_WARNINGS | The demonstrated dimensions pass, with explicit retained discovery/provider limitations. No warning can conceal a failed required goal. |
| READINESS_ONLY | Reconciled available scope and functioning observation are shown, but no admissible transition/native recovery demonstration occurred. State source limitations and actual stop reason. |
| INCOMPLETE | A required scope/goal could not complete within its limits; preserve current verified demand and every gap/unknown outcome. |
| BLOCKED / FAILED | Identity, integrity, ownership, credential, budget, unexplained coverage or required-outcome failure prevents the corresponding claim. |

Unavailable intermediate updates, unknown older carryovers, full historical quote restoration, long-history/mixed-source/soak/provider capacity, unattended machine recovery and production adoption remain outside this increment's claims. Earlier command-34/36/stress/cloud failures keep their original verdicts.

## 8. Offline/Windows qualification before any live launcher

Add focused integration tests for credential-before-initial-run creation, proposal/catalog/config binding, aggregate quote/feed budgets across generations and manual resume, CURRENT → dated → CURRENT cutover, recovered already-resumed events, same-event request reuse with retained update history, normal admission/capacity outcomes, stop/deadline precedence, failed feed with healthy saved demand, and the worker startup/authentication timing boundary.

Run owned synthetic process faults around source receipt, request commit/ACK, publication plan/commit/ACK, quote dispatch, response retention and quote commit/ACK. Include wrong/duplicate owner, missing/corrupt evidence, SQLite sharing, controller reopen, changed configuration, secret-redaction and in-flight/unknown shutdown cases. Qualify the source-pinned extracted bundle on Windows. Reuse accepted lower-level results and repeat only affected checks.

Only after those gates pass should the package expose separate ordinary-live, controlled-worker-recovery and exact-stop commands. The live invocations require explicit operator action and contemporaneous production health. They do not request a repeat of the accepted one-SPY probe or previous unchanged provider trials.

## 9. Overlay interface requirements

The companion [Overlay architecture note](https://github.com/DanArizona/mb_market_data/blob/checkpoint/mb-package-2026-10-21/docs/design/overlay_recovery_integration_20261023.md) records current source findings and the interface this controller must preserve. The existing Overlay already projects effective membership revisions and quote completion times. Its legacy halt loader accepts a static historical interval list without per-update knowledge timestamps. That is insufficient by itself for an as-known live/recovery display.

Retain stable source/experiment/journal identities, event/update IDs, original event times, knowledge/receipt times, query provenance and recovery status/gaps in a versioned read contract. Membership remains Coordinator-owned. Overlay reads cannot start collectors, publish membership, alter budgets or fetch broker/feed data implicitly. Scheduled source resumption, observed broker state and actual trade evidence remain distinct.

Overlay implementation follows backend qualification. The first read adapter should bind one explicit experimental journal and its corresponding source/recovery records. A later view combining production Uni/Focus with isolated Hot needs an explicit multi-journal merge/identity/clock contract; do not silently splice those independent histories. Live candle availability and selecting a newly admitted symbol need separate evidence. Preserve the accepted historical Overlay behavior while adding the new as-known mode.

## 10. Next implementation slice

Commands 41/42 have Windows acceptance. Finish command 43 Windows qualification of post-credential catalog acquisition and native startup binding, then wire prepared-client runtime supervision and the existing 3s/8s worker timing boundary. Implement full manual controller resume under the original identities, frozen window and cumulative budgets before the two separately invoked live profiles. The current supervisor/heartbeat still carries provider-driver/live-qualification-pending labels; distinguish accepted lower-level evidence from newly demonstrated results without relabeling old receipts. Update this version explicitly if evidence requires a different experiment; no running controller or live qualification is claimed by this definition.


## Implementation progress — first bootstrap slice

The separate [command-41 increment](../../experiments/controller_bootstrap_20261023/README.md) now implements fresh-session authentication before initial native journal/poll_run creation, immutable input/dependency/window checks, bound native request/publication/source initialization, and a private-pipe owned-process proof entry. All 53 focused local checks pass in 14.990272796000227s, with network denied and synthetic configuration/SDK. The development close-time failure remains retained. The source-pinned extraction passes 53/53 in 15.918759968999893s. Command 41 is now accepted from the completed MasterBot Windows console: 53/53 PASS in 17.217276599956676s, zero skips/errors/failures, run 20261023T155228Z-afc55817 and actual CMD prompt return. The separate operator acceptance preserves the original fixed OPERATOR_RESULT_REQUIRED report label; its saved file was not independently uploaded. All 64 bundled repository files and the original archive remain unchanged. No unchanged command-41 rerun is needed. Existing command-32/33/35/37/38/39/40 source files remain unchanged. Runtime loop, actual catalog/resolution, cumulative identity budget/one-symbol fence, manual resume, coupled worker timing/live recovery and Overlay implementation remain separate work. The caller-supplied catalog is bound but is not a live source qualification.


## Implementation progress — catalog and cumulative identity gate

The separate [command-42 increment](../../experiments/integrated_identity_20261023/README.md) implements owned bounded two-source directory retrieval, immutable exact-symbol catalog evidence and a sidecar identity gate over the ordinary shared request outbox. Local focused qualification passes 211/211 checks in 6.2588491409997005s with zero skips/errors/failures and network denied. Source-pinned extraction also passes 211/211 in 6.813594320999982s in a path containing spaces; altered/extra source is blocked before tests and the original inventory is restored. Synthetic native integration reaches effective Hot membership and acquisition, audit and matching replays. Actual process exits retain charged unknown lookups or retry normal request ACKs without another identity call. The initial invalid restriction fixture is retained as a failed development record and corrected to the existing supported API.

Three cumulative identity reservations and the first broker-confirmed symbol survive reopen, cancellation and restrictions. That first confirmation conservatively reserves the experiment's one authorization even if normal admission subsequently rejects or caps it; other facts/commands remain retained. This does not change general production admission policy. The catalog's explicit freshness guard permits nonfuture footers up to seven days old and retains source/receipt times; it does not infer daily eligibility or tradability. Directory invocation ownership and acquisition after credentials still require the coupled bootstrap. Accepted earlier runtime files remain unchanged. Command 42 now has completed MasterBot Windows acceptance: 211/211 PASS in 13.80042899993714s (runner 13.600s), zero skips/errors/failures, run 20261023T162931Z-fc6b086a and actual CMD prompt return. The saved report was not independently uploaded; the separate operator acceptance preserves the fixed OPERATOR_RESULT_REQUIRED label. All 72 bundled repository files and the original archive remain unchanged; no unchanged rerun is needed. Prepared-client injection into runtime supervision, the 3s/8s worker timing boundary, full manual controller resume and bounded live recovery remain pending. No live controller launcher is exposed.


## Implementation progress — authenticated catalog-bound startup

The separate [command-43 increment](../../experiments/catalog_bootstrap_20261023/README.md) adds an explicit owned-directory bootstrap mode. Credentials and both credential-horizon checks precede fresh-root ownership and a durable one-invocation reservation charging both source permits before acquisition. Captured source bytes and receipts precede immutable catalog binding, ordinary admission, the identity gate, initial journal and initial native `poll_run`. The session defaults to gated delivery; no RSS, identity quote, running collector or live controller is started. Uncertain/failed directory invocations remain charged. Saved successful bytes can be reconstructed read-only, but full manual controller resume is not implemented.

All 288 affected current-host checks pass in 37.30795769899987s (runner 37.210s), zero skips/failures/errors, with synthetic configuration/SDK/HTTP and network denied. Owned-process exits cover reservation, captured bytes, catalog binding and initial native registration; failed authentication, redaction, deadline precedence, catalog/ledger corruption and legacy behavior are checked. A retained 288-test development result had one fixture import error and 287 passes; the fixture correction did not alter runtime behavior. Source-pinned extraction and Windows acceptance are separate records.

This increment extends two shared files accepted in command 41: `controller_bootstrap.py` and `bootstrap_entry.py`. Default v1 public configuration identity and receipt shape remain compatible. The original command-41/42 commits, archives and pinned acceptances remain intact; historical statements that their bundled files were unchanged describe their acceptance checkpoints. The new two-file extension is covered by affected regressions here rather than relabeling those old artifacts. Startup now stops by password submission +60s even when T0 is rounded upward; neither T0 nor Tstop is extended. Prepared-client runtime supervision, the retained 3s/8s worker timing boundary, full manual resume, bounded live recovery, Overlay and broader capacity/production adoption remain pending.
