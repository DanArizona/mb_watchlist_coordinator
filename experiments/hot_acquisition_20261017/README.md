# Isolated Hot acquisition review

This increment connects the Windows-accepted Coordinator publication service to
a membership-aware Hot acquisition path. Four independent local processes run
the Coordinator, Uni, Focus and Hot against one fresh experimental journal.
Quotes are explicitly synthetic. The existing Schwab batch collector, schema-v2
store, auditor and replay projector process their real local request/receipt times.
No network, password, installation or production-journal access is performed.

In an activated `sea-green` CMD, call the bundle's absolute
`01_run_hot_acquisition.cmd` path. It verifies bundled source, runs **30 focused
tests**, and runs a bounded process proof taking roughly 20 seconds plus local
startup/testing time. Expect `Isolated Hot acquisition proof: PASS`, timing
summaries, a report path and `Finished. This command returns to its prompt.`
Every run creates new evidence under this experiment's ignored `runs` directory.
No browser or extra manually managed console is required.

## Where the implementation belongs

`market_data_extensions/sampling_acquisition.py` is review-stage **market-data**
code. It imports no Coordinator code. The cross-repository integration proof is
kept beside the accepted Coordinator experiments so it can pin both sides in one
review bundle. The runner explicitly extends the pinned `mb_market_data` package
search path to this one module. It does not install or replace a package.

The original frozen promotion experiment, production cadence primitives and
accepted Coordinator implementations remain byte-identical. After review, this
module needs integration into an isolated `mb_market_data` checkout and a bounded
Schwab-client trial before any production Hot activation. The current production
CLI has not acquired a Hot switch or a default Hot cadence.

## Polling contract

Each instance requires an explicit channel, sorted whole-second cadence,
same-session half-open window, batch size, quote fields, source label, lateness
budget and write-retry interval. There is no Hot default. The existing
production Uni `:00,:30` and Focus `:05,:20,:35,:50` contracts are unchanged.

Membership is resolved from the journal **at the scheduled slot**, then captured
with revision, complete symbol order, hierarchy hash and dispatch time. A later
revision cannot rebind an in-flight response. Each next slot reads the latest
hierarchy effective at that slot. Missing membership fails visibly; an explicitly
empty group records an `empty_membership` skip without a quote request.

The standard `fetch_quotes_batched` path provides one explicit result per symbol:
quote, invalid, missing or request_error. Results retain each batch's actual
request start and response receipt times. The journal atomically commits the
acquisition header and normalized observations. Replay makes a completed
acquisition available at its completion time, independently of its scheduled slot
and any subsequent membership change.

The scheduler calculates the next future slot after completion. It does not issue
catch-up bursts for missed slots. Dispatch beyond the explicit lateness budget is
retained as a missed outcome; it is not mislabeled as an empty group. The existing
auditor consequently continues to report the coverage gap. Client request timeout
and in-flight cancellation belong to the supplied client. Scheduling/retry waits
are interruptible. The synthetic client is bounded; live-client timeout behavior
requires its own trial.

## Durable acquisition and recovery

A canonical per-journal/per-channel SQLite sidecar stores hash-linked dispatch,
assembled-response, journal-acknowledgement, missed and unresolved outcomes.
Canonical paths and a local OS lock serialize a channel across processes. Other
channels have separate sidecars/locks and continue independently. All SQLite
handles close explicitly, including in tests and failure drills.

| Last durable state | Restart behavior |
| --- | --- |
| Empty-membership dispatch | Commit/recover the original empty skip; make no quote call. |
| Nonempty dispatch, response not durably saved | Retain an unresolved outcome and coverage gap; never silently issue another request for that slot. |
| Complete response saved, journal not committed | Commit the original saved result and timing without another quote call. |
| Journal committed, acknowledgement not saved | Verify the original header/observations and acknowledge that same acquisition. |
| Acknowledgement saved | Preserve it; a duplicate slot makes no request. |

A response received immediately before a crash may be lost if it never reaches
durable storage. The proof deliberately demonstrates that boundary. It does not
claim exactly-once network delivery across that gap. Received-and-saved evidence
is recoverable across a journal write failure. Changed membership bindings,
configuration, sidecar history, saved acknowledgements, normalized observations,
or unexpected channel outcomes fail visibly without issuing fresh quotes.

Operational SQLite errors are retained and retried. Integrity/evidence failures
stop the affected worker. Source request errors remain explicit observations;
they do not remove members or stop healthy channels. An injected Hot write
interruption test verifies that Uni and Focus can still commit.

## What the running proof establishes

The real-process demonstration uses a three-symbol Uni, one-symbol opening Focus
and initially empty Hot group. A manual MSFT request causes a Coordinator revision
and a Hot quote. A second synthetic halt source keeps demand after the manual
withdrawal. A privileged Uni cap creates an empty Hot slot. Recorded timer ticks
expire that cap, permit reentry and subsequently demote after the final withdrawal.
The journal contains five complete hierarchy revisions. Every configured slot has
an acquisition or an explicit empty skip; all channels pass the existing audit.
Two acquisition-aware replays are identical. A cutoff immediately before the first
Hot completion contains no Hot quote; the completion cutoff does.

Demonstration grids are Hot every 2 seconds, Focus every 4, Uni every 6. These are
**review-only grids**, selected to exercise all processes in a short window.
The accepted Coordinator runs with accelerated 0.2s grace / 0.5s residence,
0.35s publication lead and 0.05s local receipt polling. The poller's lateness
budget is 0.8s. None are adopted production defaults.

The synthetic client adds 150ms per Hot quote request and 10ms per Uni/Focus
request. Reports separate collector duration, journal write duration, full active
cycle, empty cycle and dispatch lateness. Mean/p95/max summaries include sample
counts; a very small sample's p95 is often its maximum. Only two Hot acquisitions
occur in the normal bounded trace, alongside empty Hot slots. This is a correctness
and local-overhead measurement, **not** sustained 30-per-minute, provider/API-budget,
many-symbol capacity or real market freshness validation.

Four additional processes deliberately exit with code 73 after dispatch, after an
unsaved response, after a saved response, or after journal commit. These drills use
an explicitly injected logical clock. The first two preserve an expected auditor
gap; the latter two recover the exact evidence without another quote request.
The 30 focused checks also cover slot-time/in-flight revisions, batching, explicit
error outcomes, full observation rollback, restart, ownership, source guards and
stop behavior. Windows acceptance is pending until MasterBot supplies its output.

Next steps are MasterBot review, market-data checkout integration, a bounded
authenticated Hot quote trial with measured provider latency, and a genuinely new
live Nasdaq qualifying-halt path. Production policy/cadence, external authentication
and deployment remain explicit follow-up decisions. Candle/viewer work is separate.
