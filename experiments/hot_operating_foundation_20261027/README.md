# First operating-release increment — October 27

The two required bounded live profiles are accepted. This increment prepares
the next fresh-session cadence rollout and makes the initial Hot operating
proposal concrete. It supplies source-pinned offline verification, a daily
review-plan CLI, deployment review, guarded after-close installation and Git
revert. The existing live-profile implementation and original accepted limits
are carried forward as evidence; they are not converted into daily operation.

## Implemented in this packet

- Explicit named cadences: legacy by default; interleaved Uni00/30 and
  Focus10/20/40/50, with the other even seconds reserved for future Hot.
- Pre-credential and atomic run-registration protection against mixed sessions.
- Per-session Health, watchdog and manual-restart cadence handling. Health
  prints complete current-source restart commands for the new profile.
- Historical audit/replay compatibility and Overlay request-error endpoints
  based on the recorded run cadence.
- Proposal-bound review plans with separate Uni, Focus and Health commands,
  source hashes, expected counts, stop/restart/status instructions and rollback.
- Read-only deployment review; after-close, idle-process source installation
  and reversible Git rollback, each behind Windows qualification and the
  separately required production-change approval.

## Proposed first Hot operating values — not adopted

| Setting | Review candidate |
| --- | --- |
| Halt codes | LUDP and M |
| Identity/admission | Exact directory/common-equity broker confirmation; normal admission and restrictions |
| Active Hot / distinct added symbols | 1 / 1 per session initially |
| Request lifetime | Through regular close |
| Cadence | Other even seconds, 24 opportunities/minute |
| Full-session Hot quote-call ceiling | 9,360; empty membership makes no quote call |
| Identity / directory ceiling | 3 / 2 |
| Feed ceiling / spacing | 390 attempts; at least 60 seconds after completion |
| Owned worker starts | At most 3 |
| Worker progress / credentials | Original 3s / 8s |
| Replacement hold / cleanup / reporting | 15s / 10s / 60s |
| Demotion grace / minimum residence | Proposed 60s / 120s; privileged cap remains immediate |

The daily values are a **proposal**, separate from the accepted 12-minute,
60-Hot-call experiment. The earlier synthetic demotion values were not adopted
production defaults; this table now explicitly proposes them for review.
Full-day provider/collector qualification is not inferred from the arithmetic.
The three existing Nasdaq snapshot/carryover/provider warning codes are retained.

## Remaining daily Hot work

The daily source/identity/admission/collector/controller integration is the next
implementation slice. This packet has no daily Hot launch command and its
plan fixes `hot_enabled=false`; editing policy JSON cannot enable it. The
original experiment's 12-minute/one-symbol/60-permit guards remain intact.
After a qualified fresh Uni/Focus cadence session, production Hot still needs
the concrete operating driver, health/recovery/deployment integration and
explicit activation approval. Manual membership follows closely and can be
built alongside the cadence observation; agreed read-only Overlay remains in scope.

## Commands in the delivered packet

57 verifies only the affected cadence/journal/Health/replay/Overlay/plan/deployment
behavior, using synthetic data and pinned test helpers with network denied.
It does not repeat command56 or either accepted live profile. On Windows the
result must have zero skips/errors/failures and return to the actual CMD prompt.

58 takes opening-r0 and Focus-r1 paths plus `--market-data-root` and `--ecfg`.
The ecfg argument is a path only: planning does not open it or ask for a password.
An optional `--output-dir` must be a new folder separate from acquisition journals.
Using today's live legacy journal for review reports
`EXISTING_SESSION_CADENCE_CONFLICT`, as expected; rollout uses a fresh dated session.

59 reviews the production baseline and deployment targets without changing
source, processes or journals. Installation is a separate `run.py install`
operation after Windows acceptance and explicit approval. The original normal
opening/closing procedures remain the operator workflow for this increment.

## Delivery qualification — October 27

The frozen packet `hot_operating_20261027_14883e.zip` has local qualification
at **233 tests: 232 passed, one native Windows sharing test skipped, zero
failures/errors**. The extracted packet also passed planning from a path with
spaces and refused extra/altered executable source before imports. The initial
isolated-environment dependency failure is retained in the packet; final checks
used the frozen source after fixing that verification environment.

Windows command57 acceptance and actual CMD prompt return are still pending.
Verification does not install source, change production cadence or start Hot.
The daily Hot driver is not included. See
[the delivery validation record](validation/operating_foundation_20261027_PREPARED.json)
for exact source/archive hashes, remaining scope and limits. The archive is
pinned to Coordinator source `a45ccaf0c4d20475115e664610a0cb73d6533755`
and market-data source `96faa13e97f6f07d7f5019fb6dd02b858eb76c76`;
this later documentation record does not change its frozen bytes.

## Command57 Windows result and test cleanup correction

The original packet's Windows command57 is **FAILED**: 233 tests,232 passed,
one error,zero skips/failures, with actual CMD prompt return. Its mixed-session
refusal test left a test-only SQLite connection open, so Windows refused removal
of the temporary journal. The transaction context manager did not close that
connection. Production store/early-check connections already close explicitly.

The corrected market-data candidate is `6b53ab1d12e4e1fdaf4deb1d70b717e13570358c`
on `experiment/hot-operating-cleanup-fix-20261027`. Only the test connection
scope differs from the previous candidate; runtime/probe bytes and limits are
unchanged. The candidate remains one ordinary commit from the production
baseline, preserving the prepared one-commit Git-revert deployment contract.
A probe retaining every real connection observes one open handle in the
original test and zero in the correction. Corrected native Windows qualification
is still pending. The original archive/result is retained. See
[the failed Windows record](validation/command57_20261027_WINDOWS_FAILED.json).

## Corrected packet qualification

The test-only correction packet is `hot_operating_fix_20261027_6b53ab.zip`.
Its unchanged 233-test operating-foundation suite passes locally at232 passed,
one native Windows-only skip,zero errors/failures (18.469804709999153s report).
The extracted packet's formerly failing test passes with six real connections
retained and all six closed after cleanup. All109 runtime/probe/helper source
references match the original packet. The original command57 Windows FAILED
result stays unchanged. Run this new folder's command57 for complete native
Windows qualification; original accepted live profiles need no repeat. See
[the correction delivery record](validation/cleanup_fix_20261027_PREPARED.json).
