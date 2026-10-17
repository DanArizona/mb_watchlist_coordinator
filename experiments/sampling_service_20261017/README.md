# Running Coordinator publication and recovery review

This increment connects the accepted source-owned request/policy reducer to a
running, serialized publication loop. A separate child process watches a local
request ledger, records due clock ticks, publishes complete schema-v2 hierarchy
revisions, and acknowledges the journal's actual commit receipt. The review is
bounded and returns to the CMD prompt. It requires no password or network.

From an activated `sea-green` CMD, call this bundle's absolute
`01_run_sampling_service.cmd` path. The runner checks pinned source hashes,
runs **28 focused tests**, then performs the real-process and forced-exit
proofs. Expect `Running Coordinator publication proof: PASS`, a report directory,
and `Finished. This command returns to its prompt.` No installation is performed.
The extracted bundle may live under `mb_market_data\output`; it does not import
or modify the enclosing production checkout.

## Behavior and storage

The existing request ledger remains the durable input history. Ownership,
restrictions, future requests, expiry, and demotion residence/grace retain their
accepted reducer semantics. The new publication ledger stores a hash-linked
sequence of plans and outcomes, bound to the exact request identity, explicit
service settings, journal path and complete starting journal prefix. Three
separate files hold requests, publication outcomes, and the market-data journal.

The runtime uses the latest recorded request/policy state. Several input receipts
may be coalesced into one complete hierarchy; their original receipts remain in
the request ledger. A no-change outcome records the processed checkpoint without
creating an unnecessary membership revision. This differs deliberately from the
older offline fixtures, which materialized every historical input as a revision.

At a future activation, request expiry, restriction expiry, or ordinary demotion
deadline, the service appends a durable tick and replays the reducer. Restart
preserves the recorded timers. A missed deadline is observed at the restart
receipt; the service does not invent a tick or market membership in the past.

An OS file lock serializes the whole cycle across processes, including the gap
between separate database commits. A leftover lock file does not imply a live
process. Operating-system handle release after abrupt process exit is exercised
by the review. All SQLite handles close explicitly for Windows compatibility.
Use local disks; network filesystems and multiple hosts are outside this contract.

## Publication and recovery contract

| Point reached before interruption | Restart action |
| --- | --- |
| No durable plan | Re-read current inputs and time. |
| Plan saved, no journal revision | Retain an abandoned-plan outcome, recheck current demand/timers, and schedule a fresh effective time if still needed. |
| Complete journal revision committed, no acknowledgement | Verify exact plan content and store-assigned publication timestamp, then acknowledge that original revision. |
| Journal acknowledgement saved | Continue from the recorded checkpoint; do not duplicate the revision. |
| Journal prefix, request history, or settings conflict | Stop with an error and preserve evidence. |

The plan is committed before the journal write. The journal atomically inserts
all three channels. A rollback leaves the request and plan available for recovery.
An acknowledgement contains the complete committed proposal, canonical content
hash and actual `published_at`; producer-to-request delivery acknowledgements
remain a separate concern. Reopening verifies every retained journal prefix and
request checkpoint. An owned journal cannot be silently adopted by a replacement
publication ledger after the original ledger is lost.

The service requires a positive explicit publication lead, because the journal
refuses backdated effective times. A known timer boundary or publication-window
end at/before the proposed effective time defers that proposal until re-evaluation.
A deadline missed during insertion is abandoned and rescheduled. Committed
future revisions are immutable; subsequent inputs get a later corrective revision.
Inputs arriving after the final pre-write check are handled by the next cycle.
There is no atomic transaction spanning source admission and journal publication.

"Immediate cap" remains the reducer's policy: it bypasses ordinary demotion
holds. Actual journal availability/effectiveness also depends on local polling,
publication lead, write latency and any outage. This review does not claim a
zero-latency cap or guaranteed promotion deadline. Residence/grace are measured
from the accepted request-replay receipts, not from eventual poller observation.

`run(stop_event, on_status=...)` uses interruptible waits. SQLite operational
failures and ownership contention report retrying status and retry; integrity or
configuration errors propagate. The runner records process status as complete
JSONL lines, including clean stop. Its child processes are bounded and restricted
to this experiment's fresh `runs` directories. It never restarts production.

## Evidence and limits

The 28 unit/integration tests use an explicitly injected future logical clock;
the pinned journal still assigns its real publication timestamps. They cover
expiry, future activation, the existing 60s grace / 120s residence configuration,
independent source withdrawal, caps, stale plans, missed effective times, full
channel rollback, retry/error handling, identity/prefix guards and prompt stop.

The separate running-process proof uses actual wall time. Its accelerated policy
is **0.4s grace / 0.8s residence**, with **0.05s local receipt polling** and
**0.35s publication lead**. These keep the demonstration short and are explicitly
not production defaults. The process creates five complete hierarchy revisions:
baseline, Hot promotion, cap removal, cap-expiry reentry, ordinary demotion. It
waits for revisions to become effective before asserting the observed sequence.
Manual withdrawal alone leaves the second synthetic halt source's demand active.

Two additional children deliberately exit with code 73 directly after plan or
journal commit. Those fault drills use the labeled logical clock. Restart must
reschedule an uncommitted plan or preserve and acknowledge the committed revision.
All three journals pass the existing audit and two identical replay passes.
No market acquisitions are made. Reopening the service preserves its outcomes.

Nasdaq records are not fetched here; the second source is labeled synthetic.
The accepted recorded Nasdaq adapter remains unchanged. Live transport,
authentication/permissions, production policy/cadence choices, load capacity,
isolated Hot acquisition, and a genuinely new live qualifying halt are subsequent
work. Candle/viewer polish is independent. MasterBot Windows acceptance is
complete: 28 tests in 2.401s, retained running proof PASS, 60 real process cycles,
five hierarchy revisions and clean prompt return. See `VALIDATION.md` and the
structured acceptance receipt. The next increment is isolated Hot acquisition.
