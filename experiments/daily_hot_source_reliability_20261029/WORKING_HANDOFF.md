# Source reliability development — resumed October 29

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

Next: freeze the source and build command 67; verify the exact ZIP extraction
and source inventory, publish under standing approval, and request one Windows
run with its actual returned CMD prompt. Original commands 63/64 remain FAILED,
the old I/O cause and ledger-change actor remain unassigned, and Windows 67,
live provider performance, concrete operating/deployment/settings review and
activation remain pending. Earlier accepted qualifications and failed results
are preserved. Manual controls and read-only Overlay follow automatic Hot;
overnight-volume reconsideration remains deferred.
