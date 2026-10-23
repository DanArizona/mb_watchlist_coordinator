# Native Hot collector and acquisition recovery

This increment connects the accepted experimental worker protocol to the real
`IsolatedSamplingPoller`, existing Schwab-shaped batch collector and schema-v2
journal. Provider responses are synthetic in every qualification run. No
credentials, broker SDK authentication, live feed or production process is used.

## Implemented behavior

- Explicit experimental journal and publication identity, fixed regular-session
  window of at most 15 minutes, one-batch roster limit and durable quote budget.
- The worker holds the generation-fenced role lease through saved-evidence
  verification, recovery and acquisition. Changed/missing manifests, sidecars,
  source bindings or native observations block instead of resetting state.
- Saved assembled responses commit without another provider call. Journal
  commit before ACK recovers the same acquisition. Dispatch-only or received but
  not durably spooled responses remain explicitly unknown and are not reissued.
- Fresh jobs resume strictly after the current time and generation resume gate.
  The existing 750ms dispatch deadline and experimental interleaved Hot grid
  remain. Past-slot quote catch-up is prohibited; missing history stays missing.
- A nonempty durable dispatch reserves one quote-call opportunity, including
  interrupted/uncertain calls. The immutable manifest binds the entire window,
  budget and roster limits; reopening cannot silently reset them.
- Client creation is lazy: only a permitted nonempty future quote dispatch can
  invoke the explicitly supplied prepared-client factory. Idle/empty work and
  saved-response recovery need no provider client. The adapter does not discover
  credentials or perform authorization. The supplied client must enforce its
  own bounded request timeout; the parent can stop only its exact owned handle.
- Heartbeats follow completed collector/idle-validation work. Idle progress is
  explicitly distinguished from quote acquisition. Provider hangs stop progress;
  owned restart retains the uncertain dispatch. Healthy foreign workers and
  Uni/Focus remain outside this driver's ownership.

The native sampling_acquisition.py and its native tests are copied unchanged
from the existing market-data experimental checkout. No production module is
installed or replaced. This first adapter uses the native full-history verifier;
it does not add an incremental cache or establish long-history recovery speed.

## Offline qualification

Run only new `37_verify_hot_collector_cleanup.cmd` from the extracted package.
It verifies the source inventory before running the affected suites. Main and
fixture child processes deny network. No password, API or production journal
is required; allow roughly one to two minutes on Windows and retain the final
summary and actual CMD prompt return.

Drills cover real child exits after dispatch, response spooling and journal
commit; exact-handle shutdown of a hung synthetic provider; generation fencing;
durable budget reuse; missing/changed evidence; empty Hot; slot/window bounds;
roster limits; native audit and matching replay. A composed synthetic recovered
Nasdaq halt passes through normal request delivery, native Coordinator
publication, the recovery supervisor and a separate native Hot collector.

Commands 32, 33 and 35 retain their accepted source-pinned results. There is no
request to repeat their unchanged packages or earlier live/capacity trials.
Command 34 retains FAILED and its original child-exit cause remains unproven.

## Remaining boundary

This is native collector integration with an explicitly supplied client factory,
not an authenticated SDK bootstrap or live-provider qualification. Password and
token handoff, noninteractive SDK startup/credential-horizon checks, bounded live
HTTP and market-hours recovery, full-day/cumulative history/mixed-source/soak
capacity, original direct-producer migration and production adoption remain
pending. Configured heartbeat/startup gates are not raised to hide slow cold
reconstruction. Production main, Uni/Focus cadence and Hot-disabled policy stay
unchanged. Windows acceptance for this new source is pending.

## Windows command-36 cleanup failure

The completed MasterBot run `20261023T084357Z-4fca6462` reports 491 tests in
55.039469900075346s, 490 passed and one error. The sole error is Windows
WinError 32 removing quotes.sqlite3 during temporary-directory cleanup in
the native-observation corruption test. No assertion failure is reported.
Command 36 remains FAILED and is not accepted.

That test used the SQLite connection transaction context without explicit
connection closure. Instrumenting all 49 connections during the isolated test,
while retaining their Python references, reproduces exactly one unclosed
connection in the original test. The correction wraps the transaction in
contextlib.closing; all 49 connections then close explicitly. It does not rely
on garbage collection, delayed deletion or ignored cleanup errors. Runtime,
native dependency, corruption rejection and qualification gates are unchanged.

Command 37 is a fresh source-pinned offline delivery with this test-only
correction. Earlier packages and the command-36 failed result remain preserved.
