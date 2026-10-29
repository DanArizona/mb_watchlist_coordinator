# Source reliability development — resumed October 29

New saved-state attachment identifies controller error IdentityStopRequired,
terminal daily_inputs_or_source_failed and stop 14:01:02.829912Z. Driver-live
then records STOPPING at 02.835425Z; outer stop at 02.842957Z is later. Thus
controller_progress_stale is downstream of an already stopping controller.
First collector exit was observed at 14:00:12.683226Z, hold until 27.683226Z,
replacement reserved 27.700905Z. The earlier exit cause and underlying identity
stop code remain unknown. IdentityStopRequired is RuntimeError outside the
source receipt exception tuple; null receipt does not exclude this source
failure. Repeated Timeout (0:00:10)! banners are deliberate faulthandler stack
snapshots, not operating deadline failures. Obtain the complete existing closed
state copy (process events, identity SQLite events, worker exit receipts and
role stacks) before another test or code change. Original FAILED remains.

Latest Windows command 67 result: FAILED 49/50, run 20261029T145255Z_87ab13e4,
complete supplied console/final JSON and returned CMD prompt. The paced owner
stopped at 63.063 seconds with controller_progress_stale, child return code 70,
no observed source cutover and no failure receipt in the final report. Windows
Job cleanup observed empty scope in .031 seconds without force. Native audit
FAILED; equal two-event replays do not qualify collection. Parent observer max
gap was .047 seconds. Earlier local PASS evidence remains within its scope.

Code review: the outer classifies any non-RUNNING driver heartbeat as stale,
including STOPPING. That label therefore does not prove a three-second stall;
it can obscure an earlier controller failure. The synthetic wrapper maps all
unhandled exceptions to exit 70, so that number does not identify the cause.
The near-one-minute timing suggests inspecting the first historical-query
transition, but does not establish that it failed. The idle-load explanation
remains a hypothesis, not a proven fix. Read this saved run's controller status,
driver-state/live/stop and thread stacks next; request no rerun or new packet
until the first failure is identified. Original I/O and ledger-change causes
remain unassigned. Production is unchanged and Hot stays disabled.

Earlier chronology follows; its pending Windows references are historical.

Production Uni/Focus opening is healthy at 09:32:07 ET (529/40/0); live Hot
remains disabled. This development uses private synthetic roots and denied
network. No broker SDK/vault/provider call, production install or main merge.

Restored Coordinator full tree equals published d4614f2. Paired native source
is restored unchanged at 5552c5d from its private bundle. Earlier local copies
were stale; that observation does not establish the prior I/O/mismatch cause.

A deliberate valid older publication-database rollback reproduces the exact
journal-prefix mismatch. Current code adds diagnostic counts/hashes without
repair or retry. Exceptions during source pre-validation now save independent
checksummed failure evidence and preserve the original caller exception.
Already-caught authority BLOCKED results still return BLOCKED. Diagnostic-write
failure preserves the original failure. Source-only readiness now reports
READY_WITH_GAPS once its own scope is reconciled; collector management remains
false. No ownership, credential/progress/hold/cleanup or pacing gate changes.

The first new paced owned proof failed after about 32 seconds on the driver
progress watchdog. Its closed journal retains nine empty-membership skips;
no source-scope reconciliation or quotes was claimed. The first CURRENT feed
was valid; admission of the startup carryover awaits the paced historical
query. All roles were cleaned up and raw native audit remains FAILED.
The test now records parent scheduling gaps and optional thread stacks to
separate blocking work from an execution-host pause. A test counter was also
corrected to use the existing identity-event kind reservation. One initial
new rollback fixture assumed two publication events but an initial no-change
outcome makes three; its setup assertion was corrected and the baseline
rollback reproduction retained the original unhandled prefix ValueError.

The second paced development run also failed the progress watchdog after
48.5 seconds. Cleanup completed, and raw native audit remained FAILED. Its
thread stacks, closed state and a 2.59-second observer scheduling gap are
retained. These measurements do not prove a particular host pause or SQLite
cause. Profiling forty pending source cycles showed 8.66 seconds of CPU work,
including repeated full validation of the same ledgers. The outer entry now
uses an interruptible 0.5-second idle wait instead of 0.1 seconds. Independent
watchdogs and every actual dispatch validation remain; no deadline or feed
pacing was relaxed. This is a candidate runtime change, not adopted production
settings.

The complete paced owned proof then PASSED in 128.912 seconds (test runner
129.127 seconds). Three actual synthetic HTTP child attempts completed in
CURRENT/history/fresh-CURRENT order, with completion-to-next-start intervals
61.066665 and 61.217264 seconds. Source status reached READY_WITH_GAPS for its
declared query scope. The native journal contains 27 Hot acquisitions, two
after reconciliation; there were 23 empty-membership skips before admission.
One identity permit and one worker start were used. Native audit PASSED and
two fresh 30-event replays matched SHA-256
49e753f1fdb8c170d8a3b395870632c37979e65254d925686138471d5651aa4b.
Scoped cleanup completed in 0.234284 seconds, without forced termination;
original Uni/Focus poll runs were preserved. Maximum observer scheduling gap
was 0.450688 seconds. No source-failure receipt was produced.

Affected source/publication/controller checks PASSED 46/46 in 16.621 seconds;
three entry/parent-loss/original-cleanup-deadline checks after the idle-wait
change PASSED 3/3 in 4.203 seconds. Together with the paced proof these cover
the fifty distinct tests selected by command 67, in separate component runs;
they are not represented as one fifty-test local invocation. No unchanged
full-size or fifteen-second recovery drill was repeated.

Frozen Coordinator source 2f56703904db10cf6c47e410f350f60cfa03656f was built
into command 67, 845541 bytes, SHA-256
7d667238bffafab036d004a5380b32c6d2e1f41d882eb0d189e6e2a4f9cf4b95.
Nine selected checks from the exact ZIP extracted into a path containing spaces
PASSED in 8.926 seconds; pre/post inventory matched and the runner selects
exactly fifty tests. The unchanged 129-second proof was not repeated. Public
equivalent source commit 421521396d5357dd7d3c2332d68597a7345f08a4 has the
identical complete tree 370601b79ef5f075e23c375bea2c1c6b6e980466 on branch
experiment/daily-hot-source-reliability-20261029.

Next: request one Windows command-67 run with its final JSON and actual returned
CMD prompt. Original commands 63/64 remain FAILED,
the old I/O cause and ledger-change actor remain unassigned, and Windows 67,
live provider performance, concrete operating/deployment/settings review and
activation remain pending. Earlier accepted qualifications and failed results
are preserved. Manual controls and read-only Overlay follow automatic Hot;
overnight-volume reconsideration remains deferred.
