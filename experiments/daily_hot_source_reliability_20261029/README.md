# Daily source reliability qualification

Run 67_verify_daily_hot_source_reliability.cmd in sea-green after extracting
this uniquely named folder under mb_market_data/output. Allow about 2.5 minutes.
Fifty focused checks include actual elapsed 60-second feed intervals; this
cannot complete as quickly as the prior eight-second collection fixture.
No password, actual vault, broker SDK, provider request, production journal,
installation, live start/resume or Hot activation is involved. Network is denied.

The owned synthetic feed supplies a startup halt, then history and fresh
CURRENT responses. The collector begins with empty Hot membership, records
empty skips, and continues to collect after the source's declared query scope
is reconciled. Three valid attempts must respect completion-to-next-start
pacing. One identity permit, one worker start, two further acquisitions after
reconciliation, native audit and two matching fresh replays are required.
Active SQLite evidence lives in private temporary storage; only closed state
is copied to runs. Such copies retain their original path identities and are
forensic artifacts, not runtime state to adopt.

Source-only readiness now says READY_WITH_GAPS when its own scope is complete;
collector management remains explicitly false. Earlier short-test RECOVERING
was appropriate before history/cutover. Known source history gaps are retained.

Source pre-validation failures save an independent checksummed
daily-source-failure.json and preserve their original caller exception.
Already caught authority BLOCKED responses remain BLOCKED. The record retains
available SQLite codes, trusted origin frames and inferred database path.
A publication-prefix mismatch additionally records counts, first difference,
revision identifiers and receipt hashes from values already read; no extra SQL,
raw payload dump, repair, retry or automatic journal acknowledgement is added.
Even an unreadable source-status ledger can leave this independent receipt;
if receipt writing also fails, the original failure is preserved. Failure
receipts are diagnostic history, not ownership, liveness or resume authority.

Profiling exposed heavy duplicate idle source validation. The outer entry's
interruptible source-loop wait is now 0.5 seconds rather than 0.1. Each actual
source/dispatch validation still runs; independent watchdog polling, 3-second
progress, 8-second credential, 15-second hold, 10-second cleanup and 60-second
report limits are unchanged. Feed pacing remains 60 seconds and call caps stay
unchanged. This candidate's loop change is not adopted production settings.

The actual paced proof passed locally after two failed progress-watchdog
development runs. Both failures, stacks and timing observations are retained.
The prior unexplained Windows I/O event is not declared fixed. A deliberate
older valid publication snapshot reproduces the earlier mismatch mechanism,
but the actor/cause of the original snapshot change remains unidentified.
Commands 63/64 keep FAILED; accepted Windows component results and unchanged
full-size/recovery evidence are retained without repeating those drills.
Native source stays exactly 5552c5d; installed production stays 6b53ab1.

Provide verification.json and the actual returned CMD prompt. Overall live
operating release, provider capacity and full-day qualification remain pending.
Concrete launch/deployment/rollback/settings review and activation approval
precede controlled live Hot. Manual membership and read-only Overlay follow.
