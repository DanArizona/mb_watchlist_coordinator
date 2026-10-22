# Coordinator growth and halt recovery qualification

Version 1 — October 22, 2026. **Design specification; implementation and new qualification results pending.** All session times are America/New_York. Numeric gates below are initial engineering targets for an isolated experiment, not measured capacities or adopted production settings.

## 1. Outcome and starting point

Demonstrate that the Coordinator can handle a bounded session of changing requests and publications, restart from its saved state, and reconcile available halt information missed during an outage. Recovery must preserve both current membership correctness and the distinction between original event time and when the system learned about it.

The two accepted Windows scaling increments remain the starting point: runtime `192eeb516c5011cd404313197e5e95e3ee05a79b`, acceptance `5024b843524c834ff39384239913cf3bb346b251`. Commands 26 and 27 are complete. Their largest 3,001-receipt fixtures mostly extend quiet history and use a small publication ledger. Full validated history replay still occurs on every read.

The October 21 interleaved live PASS used the earlier Coordinator `0417b345e2725f4e1e184d3b3202bedb846dbfca`; it does not qualify the optimized Coordinator under provider load. Existing request/publication crash tests and acquisition-history proofs remain evidence, with their original scope. The approximately 69-second cold Hot acquisition-history reconstruction observed previously is a separate cost, not fixed by request replay optimization.

## 2. Workloads to build

Use a fixed synthetic session, deterministic seed, 543 opening Uni members, 40 opening Focus members and initially empty Hot. A dated synthetic catalog supplies 64 additional identities; retain normal admission checks and session Uni retention. Exercise Hot sizes 0, 1, 40 and 41. These roster sizes are test inputs, not production capacity limits.

| Profile | Request-ledger receipts | Acknowledged membership publications, excluding anchor | Logical span |
| --- | ---: | ---: | --- |
| Ordinary activity | 1,000 | 200 | 390 minutes |
| Busy activity | 3,000 | 1,000 | 390 minutes |
| Stress envelope | 10,000 | 3,000 | 390 minutes |

Counts describe a fixture, not a forecast of real halt frequency. Receipts include accepted and rejected commands and timer ticks. Publication outcomes include plans, acknowledgements, no-change decisions and abandoned plans; report their actual counts separately. Publish only changes in applied membership; do not manufacture revisions for no-change commands. Arrange valid membership transitions to reach the listed publication counts.

Each profile contains independent manual, algorithmic and Nasdaq demand, overlapping requests for one symbol, cancellation by the correct and wrong owner, repeated identical commands, conflicting command reuse, future activation, expiry, temporary restrictions and their withdrawal/expiry, residence/grace timers, outside-Uni admission and re-entry, and session-close handling. At least 60% of receipt actions must be non-tick commands. Repeated transport submissions are counted separately from inserted ledger receipts.

Add a burst of 100 submissions over 10 actual seconds to the busy prefix. Include identical retries and conflicting IDs; count admitted, rejected, already-recorded and unresolved outcomes explicitly. A separate burst straddles expiry and a restriction boundary. Every durable input must receive a replayable disposition, even when several inputs can share one publication of current state.

Grow requests and publications together first. Then hold the request prefix fixed while adding publication history, and hold the publication prefix fixed while increasing request history. This distinguishes their costs. Quote-acquisition rows are absent from these fixtures: measure an existing large acquisition journal separately when qualifying complete process recovery.

## 3. Measurements and experimental gates

Build histories through native APIs under an explicit logical clock. Record fixture construction time separately. Measure reads, submissions and cycles with a monotonic elapsed clock; never use logical session duration as an elapsed-capacity result. Use a fresh process for each cold reopen. Record hardware, Python/source versions, seeds, inventory hashes, ledger row counts, database/WAL sizes and active-request high-water marks.

At each profile prefix measure 100 native idle cycles and 100 state-changing cycles in isolated copies, plus three fresh-process cold reopens. Report count, median, p95, maximum, CPU time, Windows private bytes and working set. Record each stage rather than only the aggregate: receipt commit, request replay, publication validation, plan, journal commit and acknowledgement. Timed state-changing cycles use a real clock and the existing review settings of a 1-second poll interval and 0.5-second publication lead.

| Check | Initial gate |
| --- | --- |
| Correctness and integrity | Every expected receipt disposition, timer boundary, complete hierarchy and publication prefix matches the reference; zero unexplained divergence or silently dropped input. |
| Idle Coordinator cycle | p95 at most 500ms; maximum at most 1 second in each profile. |
| Receipt submission | p95 at most 500ms; maximum at most 1 second outside injected fault/burst intervals. |
| Publish before effective time | Zero late journal commits, unintended plan abandonment or missed eligible publications in the ordinary/busy timing runs. Report deliberate deadline-fault results separately. |
| Single actionable request to effective membership | p95 at most 3 seconds; maximum at most 5 seconds, measured from durable receipt, when no restriction, future activation, admission hold or competing burst applies. |
| Burst settling | Correct current applied state and all input dispositions within 30 seconds after the final submission; no stale intermediate membership committed after its effective-time deadline. |
| Coordinator cold reopen | At most 10 seconds for each of three validated request/publication reopens per profile, before new work. Report acquisition-journal reconstruction separately. |
| Coordinator memory | Peak private bytes below 1 GiB per process; after warm-up, a 10-minute fixed-history idle run retains at most 32 MiB additional private bytes. Report working-set movement separately. |
| Stop and ownership release | Stop request returns within 5 seconds when no injected blocking I/O is active; a fresh owner can acquire the released OS lock. |

These gates reserve room within the requested 2-to-4-second Hot opportunity pattern and expose publication-deadline pressure. The 750ms collector dispatch gate is a separate accepted rule; it is not the Coordinator cycle budget. A timing miss is evidence to profile and improve, not permission to raise a threshold silently. Report correctness, performance and recovery verdicts separately. Ordinary and busy profiles must pass all applicable gates before the next integration trial. If stress alone fails, retain its FAILED verdict, record the last passing tested envelope and limit the subsequent trial to that envelope.

The equivalence reference is the pinned accepted runtime and existing contract tests, supplemented by hand-specified lifecycle checkpoints. Compare complete request states, decisions, memberships and publication content at the same logical timestamps. Where new recovery provenance deliberately changes payloads, compare the declared semantic fields and validate the new provenance separately. Do not rely only on final membership or hashes generated by the implementation being tested.

## 4. Recovery modes and entry conditions

Use two explicit modes with the same reconciliation engine:

* **Resume saved session:** validate the original producer, request, publication and acquisition identities and saved prefixes; preserve startup knowledge and source ownership.
* **Catch up a declared late start:** use the verified current-session opening hierarchy and explicitly create a new recovery session. Earlier same-day events are recovery candidates, unlike the current trial's baseline-only startup behavior.

An unexpectedly missing/corrupt ledger is not a declared fresh start. Preserve it, mark recovery blocked, and require a verified compatible backup or operator resolution. Never create an empty replacement that adopts an already-owned journal.

Runtime recovery is a new increment. The current Nasdaq adapter keeps the first CURRENT snapshot baseline-only and HISTORICAL receipts audit-only. Implement an explicit versioned recovery receipt/policy path; retain those existing meanings and tests. Recovered events must not be smuggled through the live discovery path by changing their timestamps or retrieval mode.

## 5. Recovery sequence to implement

1. **Enter RECOVERING.** Record session, affected components, last confirmed receipts, detection time and the suspected outage interval. Check credentials locally on Windows when required. Keep healthy Uni/Focus collectors operating.
2. **Establish one publication owner.** Acquire the existing OS lock and validate configuration, catalog/policy identity, request chain, publication chain and journal bindings. Validate available acquisition evidence before restoring that collector. A lock file's existence alone does not prove an active owner.
3. **Finish saved work.** Replay accepted requests and current timers. A committed journal revision without its ACK is verified and acknowledged once. An uncommitted interrupted plan is abandoned and reconsidered using current time and inputs. Reconcile saved response/commit evidence using the collector's existing contract; a provider dispatch with no retained response remains unknown and is not blindly sent again for a past slot.
4. **Fetch available missed-event evidence.** Query the target day's halt/resumption union and any explicit saved carryover dates. For a same-day outage, query the whole day rather than just a timestamp slice. Store original bytes and HTTP diagnostics and reject unavailable/non-feed responses explicitly.
5. **Merge facts durably.** Deduplicate by the existing stable event identity, symbol plus original halt timestamp, within source/session context. Preserve each changed observation, raw hash and query provenance. A new halt of the same symbol is distinct; a reason/resumption update is not a new halt. Resolve conflicting duplicates before admission.
6. **Issue current requests.** Apply the same catalog/identity, admission, restrictions, source ownership and capacity policy as ordinary requests. Keep event time, source retrieval time, recovery receipt time and request creation time distinct. Publish a verified complete hierarchy effective strictly after the current publication receipt, using the configured lead and deadline checks. Never backdate membership or synthesize missed quotes.
7. **Resume affected collectors at future slots.** Bind each slot to the effective hierarchy. Preserve existing missed/unknown outcomes. Previously healthy channels must have neither duplicate starts nor forced restarts.
8. **Publish readiness and remaining gaps.** Persist the completed query scope, last successful capture and every unresolved candidate/gap. Resume ordinary sampled feed observation at its allowed cadence. Recovery completion means the declared evidence scope was reconciled, not every intermediate market mutation was observed.

Do not let unavailable historical discovery block reconstruction of already verified saved membership indefinitely. Existing valid demand can continue while recovery remains INCOMPLETE; newly recovered demand must pass its normal checks. BLOCKED integrity/ownership failures stop writes by the affected authority.

## 6. Feed query scope and bounded behavior

Nasdaq documents once-per-minute updates and asks readers to query no more than once a minute. Use one shared scheduler for current and dated requests: at least 60 seconds after each completed attempt, including failures. This conservative aggregate pacing avoids multiplying requests during recovery. In a future live recovery drill allow at most 10 feed attempts and a 12-minute acquisition deadline, with a 10-second per-attempt timeout; bound any lower-level retries inside that budget. Enforce the overall deadline independently of the HTTP client's timeout, retaining an unknown outcome if an attempt cannot be confirmed complete. Three consecutive unavailable responses stop that drill as INCOMPLETE, retaining its evidence. These are experiment bounds, not a newly adopted full-day retry policy.

The documented combined query is `feed=tradehalts&haltdate=mmddyyyy&resumedate=mmddyyyy`, a union of those date selections. Use the target ET session date for both on same-day recovery. A prior-day continuing halt is not guaranteed to appear simply because today's feed was queried. Restore known carryover records and query their original halt dates within the shared budget. If the outage spans more dates than the budget permits, retain the unqueried dates and continue only in a separately bounded recovery invocation.

Unknown older carryovers cannot be proven complete from today's dated query alone. A fresh installation without verified carryover history must report that scope limitation. An empty valid response means no rows in that response, not proof of no missing events. Historical snapshots can restore the facts still supplied; missing intermediate reason/resumption changes remain unknown.

For this first isolated recovery increment retain the trial selection of LUDP/M and request lifetime through the target regular-session close. Consequently, a same-day qualifying halt already resumed can still justify Hot now until close. Admission needs positive evidence of the selected original reason; a later T3/resumption row alone is insufficient. Retain unresolved rows for review rather than guess. Prior-day rows supply context; renewing them as today's demand requires an explicit carryover policy and is outside this increment. Final production selection, lifetime and carryover rules remain open.

Store scheduled quote/trade resumption times as source facts. A scheduled resumption, a broker status change and an observed new trade are separate observations. Do not infer a guaranteed release at halt time plus five minutes.

## 7. Recovery status contract

| Status | Meaning |
| --- | --- |
| RECOVERING | Validation, saved-work reconstruction or declared query work is in progress. |
| READY | Local reconstruction and declared recovery scope complete, with no outstanding gap/candidate in that scope. Sampled-feed limitations still apply. |
| READY_WITH_GAPS | Processes can operate and all planned queries completed; incomplete event trace, ambiguous candidates or carryover limitations remain explicitly recorded. |
| INCOMPLETE | A query/date, provider evidence reconciliation or other recovery step could not finish within its bounds. Verified existing demand can continue. |
| BLOCKED | Integrity, identity or single-owner conditions do not permit writes by the affected authority. |

Report local-state readiness and discovery completeness separately. Do not collapse READY_WITH_GAPS or INCOMPLETE into an unqualified healthy/complete label. The recovery report names every unresolved item and the next permitted action.

## 8. Fault drills and required outcomes

Run against copies of the ordinary and busy prefixes. Select three crash positions per boundary (early, middle and late history); extend stress-prefix drills only if a smaller prefix exposes growth-dependent behavior.

| Interruption or adverse input | Required outcome |
| --- | --- |
| Producer receipt saved before request delivery; request saved before producer delivery ACK | Idempotent delivery under the same event/command identity, no second source request. |
| Coordinator after plan, after journal commit, after ACK | Existing native semantics retained: abandon/replan, verify/ACK same revision, or idle respectively. Re-evaluate expiry and restrictions on return. |
| Collector dispatch, response saved, journal commit and local ACK boundaries | Reuse saved evidence where the native contract permits; ambiguous dispatch remains unknown; no automatic past-slot provider call. |
| 5-minute and 30-minute feed outages; late start at noon | Recover available selected same-day rows, including already-resumed examples; keep original event times and current recovery receipts. |
| Repeated query, two halts of one symbol, reason/resumption updates, conflicting duplicate rows | Stable deduplication; distinct halts remain distinct; updates retain provenance; conflicts do not silently admit. |
| Outside-Uni, unknown symbol, changed catalog, rejected admission, current restriction, expired request | Normal policy outcomes preserved; no recovery bypass. |
| HTTP timeout, HTML challenge, truncated XML, empty valid feed, missing date and previous-session carryover | Explicit availability/scope result, bounded attempts, retained bytes/diagnostics and honest gaps. |
| Lost/corrupt ledger, rehashed false admission, foreign journal revision or changed identity | Fail before a new publication; preserve original evidence and unaffected channel operation. |
| Second authority, SQLite busy, disk/write failure, backward clock and session rollover | Single owner, bounded/reportable retries, no partial hierarchy, no stale-session request or publication. |
| Stop during discovery or a pending plan | Bounded owned shutdown, replayable state on reopen and actual CMD prompt return. |

Keep injected faults separate from baseline performance samples. Verify originals' hashes before/after, native audit, repeated fresh-process replay, exact revision/response bindings, and both missing and duplicate outcomes. Repeat only affected qualifications when implementation changes.

## 9. Implementation order and completion criteria

1. **Next coding increment:** implement the deterministic rich-history builder and measurement/report runner, starting at 1,000 receipts/200 publications. Profile the accepted runtime before selecting another optimization. Extend to the busy/stress prefixes with the same contracts. Capture failures without rewriting accepted records.
2. **Recovery implementation alongside it:** add the explicit recovery receipt, query manifest/watermark, idempotent reconciliation and status/report contract. Reuse the shared histories and fault hooks. Historical admission is a deliberate versioned change, not a modification of baseline-only trial semantics.
3. **Offline qualification:** network denied; validate local and extracted bundles, full relevant integrity/equivalence and fault checks, then a 10-minute actual-elapsed busy-tail/memory exercise. Pin all source/reference inventories. A fixture-generation timeout is a retained failure, not a partial PASS; give each profile a 60-minute construction budget and each qualification invocation a declared overall timeout.
4. **MasterBot Windows qualification:** one uniquely named extracted package, no password/API/production journal. Check native SQLite file cleanup and owner-lock behavior, all measured reports and actual CMD prompt return. Keep timing gates distinct from correctness verdicts.
5. **Updated-system trial:** after changed paths qualify, prepare a separate bounded integration package using the optimized Coordinator. Start with saved/synthetic recovery evidence and live quotes only if needed; no requirement to wait for another genuine halt. A live Nasdaq reconciliation test has its own paced feed budget. Declare source pins, quote budget, stop command and complete duration before launch; obtain fresh production health. Review audit/replays, timing, gaps and unaffected production outcomes afterwards.

The finite exit for this increment is: profile envelope measured, gates classified honestly, recovery fault matrix passing locally and on Windows, and updated integration evidence reviewed. Failure produces a bounded follow-up tied to the measured bottleneck. Successful experimental qualification still leaves production rollout, operating limits, supervision/backup policy and Hot activation as separate decisions.

## 10. Evidence anchors

* Current implementation: `sampling_request_store.py` (`validated_history`), `sampling_requests.py` (full reducer), `sampling_service.py` (`_read`, `cycle`, ownership and crash hooks), `nasdaq_sampling.py` (startup floor, HISTORICAL audit-only, stable event ID).
* Accepted records: `experiments/sampling_scaling_20261021/validation/windows_qualification.json` and `experiments/sampling_replay_scaling_20261021/validation/windows_qualification.json` in this repository; market-data checkpoint records under its corresponding experiments and `experiments/interleaved_load_20261021/validation/overrun_archived_review_20261021.json`.
* [Nasdaq RSS refresh and query guidance](https://www.nasdaqtrader.com/Trader.aspx?id=TradeHaltRSS), checked October 22, 2026.
* [Nasdaq dated-query examples](https://www.nasdaqtrader.com/snippets/tradehaltaccordion.html), checked October 22, 2026: current-day selection, original halt date, resumption-date query and combined union.
* [Nasdaq halt and resumption field definitions](https://www.nasdaqtrader.com/Trader.aspx?id=TradeHaltCodes), checked October 22, 2026: initial halt date/time and scheduled resumption fields.
