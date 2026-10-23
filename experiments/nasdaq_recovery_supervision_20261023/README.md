# Paced feed retrieval and isolated recovery supervision

## Windows command 34 failure and corrective command 35

The completed MasterBot command-34 run FAILED: 432 tests, two errors and one
failure in 31.085244499961846s. Two checks lost the expected healthy worker
handle; another reported RECOVERING instead of READY_WITH_GAPS. The original
stderr was discarded, so that console does not establish the exact child-exit
cause. Its failed result remains retained; command 34 is not accepted.

Inspection found a reproducible heartbeat failure path: an ordinary reader can
briefly prevent replacement of an existing file on Windows. Previously, one
such exception escaped the worker and ended it. The corrective writer retries
only Windows errors 5/32/33, using the same already-flushed temporary file,
for at most 250ms/26 attempts. It preserves the previous complete record on
exhaustion, propagates other errors and never grants health without a valid
fresh heartbeat. Heartbeat/startup/staleness/restart limits are unchanged.

The owned-worker wrapper now drains stderr while retaining at most its last
8 KiB, saves the exact handle's exit code/reason to a generation-specific
exit receipt, and includes that receipt in subsequent supervisor reports.
Unhealthy-worker reports also expose heartbeat age/validation information.
Healthy periodic status receipts do not acquire changing heartbeat timestamps.
Tests retain these details in assertion failures instead of only raising an
unhelpful NoneType exception. This addresses the reproduced failure mode.
The completed corrective Windows run passes all 438 checks, including the three
previously failing checks and the native sharing test. The original child-exit
cause is not retrospectively proven.

Command 35 adds deterministic transient/persistent sharing-conflict cases,
same-process survival and bounded exit-diagnostic checks. One additional check
holds a real reader open and releases it during retry on Windows; it is skipped
on other operating systems. Reports count passed/skipped/failed checks explicitly.

Microsoft's [file-sharing contract](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilea)
documents that rename/delete access requires compatible sharing on open handles.
No live RSS or broker request was made while investigating this failure.

This increment implements a bounded current/dated RSS acquisition client and an
isolated recovery authority. It orchestrates retained feed evidence, normal
source-owned request delivery, native Coordinator publication and registered
experimental worker health. Production/main, credentials, journals, Uni/Focus
processes and polling cadence are not changed by this delivery.

## Feed evidence and limits

`FeedRecoveryTransport` binds one ledger to the target date, explicit dated-query
manifest, fixed HTTPS endpoint and review limits. All current and dated requests
in the experiment share this ledger. It cannot coordinate unrelated clients or
older shadow programs; do not run another feed client alongside it.

The review defaults are at least 60 seconds after each completed attempt,
10 total attempts, a 12-minute acquisition window, a 10-second hard attempt
deadline and a stop after three consecutive unavailable attempts. Limits may be
made stricter, never silently raised. There are no hidden HTTP retries, cookies,
redirect following, browser challenge handling or authentication. Access-denial,
redirect and server Retry-After responses stop the bounded window explicitly.

One hash-chained SQLite stream retains starts, permitted HTTP diagnostics,
bounded body chunks and computed outcomes. HTML, malformed/truncated XML,
invalid fields, future halts, conflicting rows and valid empty RSS remain
distinct. Failed evidence is never interpreted as an empty valid halt list.
Every read revalidates hashes, pacing, bytes and normalized outcomes. Capture
hashes and source receipt acknowledgements bind ingestion to the saved evidence.

`BoundedFeedClient.step()` runs HTTP in one exact owned subprocess and returns
without waiting for the response, so native timer/publication cycles can
continue. The parent and worker each enforce an independent deadline. The
worker holds an OS network lease and checks a durable reservation token before
dispatch. A controller restart must wait for that lease or fence the unfinished
attempt as unknown after release. Unknown outcomes retain any committed bytes
and begin a conservative new cooldown; stale delayed workers cannot dispatch.
Monotonic cooldowns supplement saved UTC deadlines, including a conservative
60-second wait when observing a completion after reopen or from another owner.

Real HTTP requires explicit `allow_network=True`. Qualification uses injected
HTTP adapters and synthetic child jobs that deny network. No live HTTP/RSS
access or market-hours result is implied by this package.

## Recovery authority and status

`NasdaqRecoverySupervisor` validates the original request, source, delivery,
publication and native journal identities before advancing work. A bounded
`run()` holds one OS authority lease. Exact saved source/request/publication
commits are replayed and acknowledged; no past quote request is reconstructed.
The accepted direct v1/v2 and external v3 source identities retain their meanings.
`reconcile(include_recovery=False)` is a new optional live-only queue gate; its
default behavior remains unchanged.

Each explicit acquisition window establishes CURRENT baseline, performs every
declared dated query and obtains a later CURRENT cutover. Prior receipt-stage
query completion cannot substitute for fresh dated work in a new outage window.
New recovered commands wait for that window's complete ingested query scope;
live discovery and already committed demand can continue independently. Same
halt IDs remain duplicate-safe across sources, updates and interrupted ACKs.

An exhausted or interrupted window is not reset. A later separately authorized
bounded recovery invocation explicitly creates new transport/supervisor ledgers
while reopening the verified original source/request/publication/delivery
ledgers. Five- and thirty-minute outage tests use this explicit path. Missing
or corrupt original state is blocked rather than replaced.

Local effective membership, declared-window discovery reconciliation and worker
health are reported separately. Native publication must be verified, its
effective time reached, pending work resolved, every current-window query
ingested, CURRENT cutover fresh and registered worker progress valid before a
ready status is possible. Normal rejections, unresolved reasons, unknown
carryovers and unavailable/intermediate feed intervals remain explicit gaps.
Recoverable transport gaps remain INCOMPLETE while the bounded loop may retry;
terminal/budget/unknown-owner outcomes stop it. BLOCKED integrity/ownership
failures do not advance membership. Readiness never means restored historical
quote coverage or every intermediate exchange update was observed.

## Process supervision scope

`ManagedRecoveryWorker` supports only an explicitly registered
`experimental_hot` role. It uses immutable fenced generation jobs, an OS role
lease, identity-bound progress heartbeats and a durable start budget (three
starts by default, including the first). Healthy owned workers are kept;
healthy prior-generation processes are observed without duplicate starts or
PID-based termination. Stale foreign leases block. Failed or overdue owned
workers can be stopped/restarted using their exact Popen handles. Missing
registry state is not a fresh restart budget.

Every new job specifies a strict future first eligible slot and no past-slot
catch-up. Its slot grid is the existing experimental interleaved Hot grid
(:02/:04/:06/:08, etc.); this does not adopt that cadence in production.
Stop/shutdown affects owned handles only. A healthy worker belonging to an
earlier controller is deliberately left running; the new controller cannot
kill it through a retained PID. Uni/Focus are not accepted as managed roles.

This delivery qualifies the worker protocol with a real, network-denied,
no-acquisition process fixture. The actual broker Hot collector does not yet
implement this new job/heartbeat protocol. Its driver integration, provider
evidence reconstruction and production process adoption remain separate work.
Reports retain `provider_collector_driver_qualification_pending`, so protocol
readiness is not an unqualified production-ready or live-Hot claim.

## Offline Windows qualification

The source-inventory-pinned `35_verify_nasdaq_recovery_worker.cmd` is accepted
on MasterBot Windows: 438/438 PASS, no skips/errors/failures, in
34.959442999912426s, with actual CMD prompt return. No unchanged rerun is needed.
It runs the affected suites and isolated real child-process fault drills. No
password, API, credentials or production journal is used. Temporary process
fixtures start/stop without acquiring market data. Allow roughly a minute on
Windows, then retain the completed summary and actual CMD prompt return.
No unchanged command 33, command 32, prior capacity workload or live trial is
requested. Windows acceptance for these pinned runtime/test bytes is complete.

Checks cover shared pacing, both deadlines including an orphan HTTP worker,
monotonic reopen cooldown, stop during HTTP, terminal/unavailable/empty bodies,
HTTP metadata filtering, corruption and rehashed outcomes, CURRENT cutover,
fresh query scopes, lost source/publication ACKs, normal admission/rejections,
5/30-minute outage windows, unchanged healthy processes, owned-worker restart,
stale/foreign ownership, durable restart budgets, future slots, missing state,
status-write failure, bounded stop and native expiry while a real HTTP fixture
child is still outstanding. Native audit and matching replays are included.

## Remaining qualification and primary references

Live HTTP response verification, the actual broker collector driver, complete
acquisition-evidence recovery, original direct-producer migration, market-hours
recovery trials and full cumulative source-history/mixed-source/memory/soak/
provider capacity remain unqualified. Earlier failed stress timing and cloud
publication-head evidence retain their original verdicts.

Nasdaq's [RSS setup guidance](https://www.nasdaqtrader.com/Trader.aspx?id=TradeHaltRSS)
specifies once-per-minute updates and queries no more than once a minute.
The [official query examples](https://www.nasdaqtrader.com/snippets/tradehaltaccordion.html)
document current, halt-date, resumption-date and combined union selections.
Both were reviewed for this increment. Only these documentation pages were
retrieved during development; the actual trade-halt feed was not queried.

## Original command-34 extracted qualification (historical)

All 432 affected checks PASS from the final source-pinned package extracted in
a path containing spaces, in 19.322003510000286s. The extracted inventory matches
the final checkout runtime/test bytes, and an altered source is refused before
tests. These checks include actual isolated subprocesses with synthetic inputs;
no live feed, credentials or broker API was used. Native audit/replays pass.

Delivery: `nasdaq_recovery_supervision_20261023_043222_f640c7.zip`, 205,269 bytes,
68 files, SHA-256 `6d3da546d7de6280d46811cd74cb74fa9a8988006521cf5156a64dfa8b672763`.
Windows command 34 subsequently FAILED as recorded above. Earlier command 33
remains accepted for its source pin. The exact delivered README and inventory,
final extracted report and superseded intermediate checkout report are retained
under validation. No qualification gate is raised by this increment.


## Completed Windows acceptance — command 35

The operator supplied the completed MasterBot/sea-green run
`20261023T052046Z-a0d65acb`: 438/438 PASS in 34.959442999912426s,
zero skipped tests, errors or failures, network denied, production access false
and actual CMD prompt return. This includes the native Windows sharing test and
the three checks that failed in command 34. The supplied console, not an
independently uploaded report file, supports this acceptance. The original
command-34 FAILED verdict and unproven original child-exit cause remain retained.

Acceptance changes documentation/records only; no runtime, tests, archive,
source inventory, health gate or qualification limit changed. Commands 32/33
and command 35 require no unchanged rerun. Next integrate the actual broker
Hot collector and saved acquisition evidence with this worker protocol, qualify
that changed path offline/on Windows, then perform separately bounded live
HTTP and market-hours recovery checks. This is not complete production recovery
or provider capacity.
