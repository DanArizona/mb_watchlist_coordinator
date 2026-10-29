# October 29 resource pause — unfinished operating/capacity work

The user requested stopping and preserving all work. Do not resume until the
user asks. Development/test activity is stopped; the last owned unittest
session was interrupted (exit 130) and has no final verdict. No new Windows
packet, installed source, adopted setting, real API/vault access or Hot
activation occurred. Production Hot remains disabled.

## Preserve the accepted baseline

Command 62 remains Windows accepted: 67/67, zero skips/errors/failures, actual
CMD return. Source Coordinator `6ebf8d1ada2802e4adf2ccb21fd596e0a5d19558`,
native `3cc91ebb7d2b7bd26d4c133bb839f2c63281ac0e`. Its acceptance record is
public as `7d31b850c21b897ba71348d03e4bd33a3a21c14c`. The original failed
Windows packets remain FAILED. No unchanged command-60/61/62 or accepted live
profile repeat is needed.

The accepted controller checkout remains `mb_watchlist_controller`; these
changes are isolated in `mb_watchlist_daily_operating` on
`experiment/daily-hot-operating-20261028`. Companion native WIP is
`mb_market_data_daily_operating`, branch
`experiment/daily-hot-capacity-20261028`, commit
`1e2699a13abd83632ae334ddb99a3393a477bffa`. New Coordinator WIP requires this
native WIP, not the accepted 3cc91eb source. Do not mix them.

Coordinator publication is authorized under the standing approval. Companion
native WIP is not authorized for public publication and is preserved in the
private pause artifact as a Git bundle. It is not installed anywhere.

## Implemented but not released

- `daily_operating.py`: independent outer owner uses accepted gated Windows
  Job Object / POSIX owned process-group scope. It has fixed close, cleanup
  10s and reporting 60s bounds; separate fresh reporting after producers exit;
  saved stop/result, read-only status, bound cooperative stop and no PID
  adoption or automatic restart. Healthy Uni/Focus/Health are outside its scope.
- `daily_operating_worker.py`: gated controller/reporter entries, outer-owner
  lease/freshness fence, RAM/pipe secret handoff. `OperatingController` keeps
  final reporting outside the active controller scope. Initial six process
  tests passed in 23.761s, before later capacity changes; this is not final
  operating-release qualification.
- `daily_operating_review.py`: public proposal/configuration from actual
  published anchors and a fresh retained directory. No prompt, provider or
  state initialization. Three early tests passed in .654s. Existing daily
  claims now must match before a new review can be produced.
- Capacity fixture generates an explicit **synthetic seed**, then executes
  only the last two native acquisitions. It does not pretend the 9,358 seed
  acquisitions were collected, execute a real full day or qualify a provider.
  Expanded shape: 600 opening Uni / 40 Focus, one added NVDA, 7,000 extra
  directory entries, 780 Uni + 1,560 Focus + 9,360 Hot records and 542,099
  observations. Background rows and complete normalized quote shapes are seeded.
- Native v2 verification re-reads all scoped persisted event/header/observation/
  skip values and reuses derived immutable parsed state for unchanged prefixes.
  New/tampered rows and changed membership are checked. Batched receipt reads
  replace per-acquisition queries. No head/mtime/size-only shortcut and no
  persistent trust cache. The v2 chain binds the exact native-writer JSON bytes.
- Daily dispatch uses the immutable state validated for the current synchronous
  dispatch; callbacks cannot borrow an old persisted dispatch. Redundant no-op
  reads were removed. Startup recovery checks the existing state under the
  native lock before adding run provenance. Original call caps, late-dispatch,
  no-catch-up, credential/progress/hold limits remain fixed.
- Daily admission uses a compact exact-symbol-set digest in ledger identities.
  The full immutable catalog set remains the ordinary admission input. Raw
  directory bytes are still rechecked. Existing experiment policies remain
  unchanged. `verified_public_sha256` reuses the original parsed digest only
  after byte validation. This avoids serializing thousands of symbols into
  every nested identity. This changes candidate daily identities: fresh-session
  deployment only; no automatic upgrade/reset of older daily state.

## Evidence and unresolved problems

All original logs are in `validation/`; `pause_state.json` inventories them.
The latest combined suite was interrupted during a history-reader case. No
final PASS, total-test count or acceptance may be inferred from completed lines.

The initial 256-target growing probe stopped at acquisition 185 after 184
completed measurements, with an acquisition-head mismatch. A separate isolated
200-step repeat completed. A seeded workspace full-prefix test also hit an
outcome mismatch; an equivalent run with active SQLite in executor temp storage
completed. The cause of the workspace failures is not established. Retain raw
errors; do not weaken consistency checks. Run large active SQLite workloads in
private temp storage and copy evidence only after all connections close.
Retained copies contain original absolute logical paths and are forensic
artifacts, not directories to adopt/resume as live state.

The original full Hot-prefix baseline took 10.074s cold preparation and
29.616/31.531s per tail tick. Initial cached stages still failed limits and are
retained. The Hot-only, sparse-quote stage reached 2.197s cold preparation and
.848/.873s ticks; that was not representative full-journal qualification.

Latest **representative** probe (`capacity_full_background_3.log`) is still
NOT QUALIFIED: cold preparation 2.766s, ticks 1.425/1.527s, but native
state-prepare plus spool checks were about .778/.892s, exceeding the unchanged
.75s dispatch budget. Actual owned-worker cold startup within the complete
three-second job gate has not been demonstrated. Final native audit/two replays
over the complete full-size fixture and representative provider capacity are
also pending. Do not call this a usable full-day release.

Earlier affected checks: native reader first development run 19 cases FAILED
(6 failures/1 error: immutable tuple/list comparison blocked callbacks), fixed
with immutable list-value comparison semantics; subsequent 19/19 passed in
13.872s. Eight early integrity cases passed in 10.755s. After dispatch-path
work, 27 affected collector/reader cases passed in 19.991s. Thirty-six store
cases passed in 1.650s after the initial Mapping-runtime optimization. Those
results precede later changes and do not replace the interrupted final suite.
Two more integrity cases now cover cold formatting edits and an out-of-band
provider callback, but their final suite has not completed.

## Resume in this order

1. Read this handoff and `validation/pause_state.json`; verify both WIP heads.
2. Complete affected tests using Coordinator/new-native/test paths below. Keep
   actual failures and do not repeat the accepted old 67-case packet for continuity.
3. Profile remaining full-shape pre-dispatch overhead. Current fixed .75s/3s
   gates must pass; do not raise deadlines or hide gaps to make a benchmark pass.
4. Demonstrate a cold, actual owned authenticated worker at full history size;
   include real job-start/import/auth/first-native-work elapsed time. Preserve
   unknown/assembled response accounting and budget across restarts.
5. Finish full-fixture native audit and two fresh matching replays, plus honest
   CPU/storage/capacity evidence. Separate synthetic sizing from live/provider
   qualification. Windows sizing remains pending.
6. Finish operator CLI, packet 63 inventory/builder, lifecycle/parent-loss/
   stale-status/report-timeout coverage, Windows handoff, deployment/rollback
   review and explicit settings/activation approval. No live operation yet.

Development import paths (bash):

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/workspace/scratch/6ce939acb4eb/mb_watchlist_daily_operating/src:/workspace/scratch/6ce939acb4eb/mb_market_data_daily_operating/src:/workspace/scratch/6ce939acb4eb/mb_watchlist_daily_operating/tests python3 -B -m unittest -v test_daily_admission test_daily_operating_review test_daily_session test_daily_history_reader test_daily_collector
```

Accepted production state remains unchanged: installed mb_market_data main
6b53ab1; October 28 interleaved full-session audit/replay passed. October 29 r0
was accepted at 529/0/0; fresh morning credentials, OV, Focus/r1 and dated
poller/Health starts remain pending. A synthetic October 30 fixture is not a
production date advance. Priority remains automatic Nasdaq Hot, then manual
membership, then read-only Overlay. No deferred OV work was revived.
