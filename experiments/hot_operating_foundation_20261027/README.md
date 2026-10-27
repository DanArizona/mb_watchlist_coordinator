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
Daily Hot implementation can proceed alongside the fresh-session Uni/Focus
cadence observation. Production Hot needs that qualified session, the concrete
operating driver, health/recovery/deployment integration and explicit activation
approval. Manual membership follows closely and can also be built alongside
the observation; agreed read-only Overlay remains in scope.

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

## Windows acceptance — October 27

The corrected packet `hot_operating_fix_20261027_6b53ab` is **Windows accepted**:
233/233 tests PASS, zero skips/errors/failures, runner11.972s/report12.311999999918044s,
Python3.12.13/sea-green, and actual CMD prompt returned. The reported market-data
commit `6b53ab1d12e4e1fdaf4deb1d70b717e13570358c`, Coordinator commit
`5566cc8d52024d899955612c5bc15d1171cf7f24` and release SHA match the frozen packet.
No unchanged qualification or accepted live-profile repeat is required.

The original packet's command57 **FAILED** remains preserved:232 passed/one
WinError32 during test-owned temporary SQLite cleanup. Only that test's connection
scope was corrected; runtime, limits and immutable archives were unchanged for
acceptance. Full retained records:

- [Original Windows failure](validation/command57_20261027_WINDOWS_FAILED.json)
- [Correction, local qualification and extracted handle proof](validation/cleanup_fix_20261027_PREPARED.json)
- [Complete Windows acceptance and evidence limits](validation/command57_20261027_WINDOWS_ACCEPTED.json)

The emitted report's raw `remaining` list is preserved. Its Windows-result/CMD
item is now complete in this separate acceptance record. Source/production
cadence installation has not happened. Next run command59 for read-only source
and qualification-marker review while existing polling continues; review the
result before separate production-change approval. Proposed operating values
remain unadopted, and the daily Hot driver remains the next implementation slice.
