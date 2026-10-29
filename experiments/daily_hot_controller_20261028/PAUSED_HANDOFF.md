# Daily controller work — paused October 28, 2026

The user requested an immediate pause and saving all work while resources refresh
(approximately 1 hour 37 minutes). Development and verification are stopped.
This is an incomplete development checkpoint, **not a qualified release**.

The accepted command-60 backend (138/138 Windows) and command-61 daily
feed/collection APIs (87/87 Windows) remain accepted. Do not repeat those
unchanged packets or the accepted live profiles. Production Hot remains disabled;
no production source, settings, credentials, journal or process was changed.

## Saved work

- `daily_worker_view.py`: worker-side verification of the original daily
  binding, catalog, source/admission and publication ledgers without taking
  the lifetime publication lease. Short publication-lock contention is retried
  for at most 0.2 seconds; other failures remain blocking.
- `daily_supervision.py`: sealed controller state and invocation history,
  charged starts before process creation, three cumulative starts, private
  stdin handoff, independent identity process, controller/worker fences and
  persisted fifteen-second replacement hold using wall and monotonic clocks.
- `daily_authenticated_worker.py`: separate collector/identity/report roles,
  synthetic-injectable SDK seam, original three-second first native progress
  and eight-second credential gates, parent-loss/stop/close fencing, native
  collector response recovery, and bounded read-only audit/replay reporting.
- `daily_controller.py`: source/identity/Hot ownership, independent worker
  monitor, explicit manual resume with original ledgers, source integrity vs
  ordinary feed unavailability, saved status and persistent incidents, owned
  cleanup and final reporting. No operator live launcher is provided.
- Two synthetic process fixtures and new controller/supervision tests.
- Original retained development logs and the structured development record
  in `validation/`. None are to be rewritten into a passing verdict.

The implementation is based on local Coordinator
`19026ba81d739faf3a8d44f643f221eec769d45a`, whose tree matches public
`a45edb8cf12e6c260d8e678ceb85119a6ce87068` on
`experiment/daily-hot-runtime-20261028`. Native source remains
`3cc91ebb7d2b7bd26d4c133bb839f2c63281ac0e` in the sibling
`mb_market_data_daily` worktree, based on installed production `6b53ab1`.

## Verification at pause

- The initial five-process-test pass was 4/5; a reproduced intermittent
  `ServiceBusy` exposed a genuine brief publication-read collision. Both
  controller and worker publication access now retry only lock entry within
  0.2 seconds, and source initialization precedes Hot worker startup.
- The corrected initial five process tests passed 5/5 in 3.899 seconds.
- Nine new supervision/ownership unit tests passed in 3.593 seconds.
- The last 26-test controller run was **interrupted on the user's pause
  request**, tool exit 130. It has no final suite verdict. Its original
  `development_4_INTERRUPTED.log` is retained verbatim.
- Before interruption, the latest run showed passing actual parent-loss
  fencing, hung quote/SDK-close bounds, credential/authorization cases,
  durable rate-limit stop, fifteen-second owned-worker recovery (including
  saved response recovery), and manual resume. Those individual results do
  not establish whole-suite acceptance.
- The coupled feed/identity/native test still reports an ERROR. Its known
  fixture defect is passing `query.query_id` to
  `NasdaqRecoveryReceipts.record`; that method requires the `RecoveryQuery`
  object itself. **This has deliberately not been fixed after the pause.**
- Earlier failing fixture assertions expected a provider-call log to imply
  a committed observation, and expected synchronous resume status before the
  monitor's first check. They now wait for the actual native commit/status.

## Resume here

1. Read this checkpoint and retained logs; fix the known query-object fixture
   call before rerunning the affected coupled test. Inspect its native
   audit/report/replay result; do not claim it passed from earlier stages.
2. Finish affected controller and ownership tests. Review actual parent loss,
   all cleanup bounds, clock/binding changes, cumulative start accounting,
   provider-stop reopening and reporting behavior. The new code is still WIP.
3. The short coupled proof uses one actual synthetic HTTP CURRENT baseline
   and one saved historical capture, then the owned identity and collector
   processes. It does not bypass sixty-second live feed pacing or claim a
   fully reconciled feed. The separate complete three-attempt source proof
   is already Windows-accepted in command 61.
4. When tests pass, build source-pinned **offline command 62**, run it locally
   and from an extracted path with spaces, retain original failures and
   produce a Windows packet. No command-62 packet exists at this pause.
5. Publish ordinary Coordinator work under the user's extended standing
   approval; do not ask again per file. New native publication is outside
   that specific extension. Main merges, destructive Git operations and
   production changes remain separately approved actions.
6. Complete representative full-day capacity, outer operator/deployment
   packaging, explicit settings and activation review before live daily
   operation. Manual membership and read-only Overlay follow closely.

Local focused check (development only, no actual network/SDK/vault):

```bash
PYTHONPATH=src:/workspace/scratch/6ce939acb4eb/mb_market_data_daily/src:tests \
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest test_daily_controller test_daily_supervision -v
```

The October 29 opening r0 is already accepted at 529/0/0. Morning credential
and source preflight, fresh OV, Focus/r1 publication and the dated interleaved
Uni/Focus/independent Health starts are still morning work. Do not activate Hot
or repeat the completed October 28 closeout while restoring this context.
