# Bounded market-open daily-path check

This candidate runs the public daily launcher and its existing owned
controller, real Nasdaq source, exact-symbol admission gate, authenticated
identity/collector roles, native journal and independent final reporter.
It uses a fresh isolated journal with copies of that day's actual r0/r1
proposals. It never opens the production quote journal or controls the
production Uni, Focus or Health processes. There is no installation step.

| Bound | Value |
| --- | --- |
| Collection | One dated 180-second window on the accepted Hot seconds |
| Startup lead | 45–55 seconds; start/end at a non-Hot ten-second boundary |
| Review to acquisition stop | At most 235 seconds, including password entry |
| Hot provider calls | At most 72, one active/distinct admitted symbol |
| Identity quote permits | At most 3; normal broker identity confirmation |
| Nasdaq feed | At most 4 attempts; original 60 seconds after completion, 10-second HTTP bound |
| Public directory preparation | Two fixed downloads, no retry; at most 10 seconds each |
| Worker starts | Original maximum 3 with the full 15-second replacement hold |
| Outer invocation/resume | One; no automatic outer restart or manual-resume command in this trial |
| Other deadlines | Original 3-second progress, 8-second credential, 3-second broker request, 10-second cleanup, 60-second independent report |

The 3-second first-work gate starts at the owned worker launch. An idle tick
still validates the native/publication state; credentials alone are not
progress. The future collection window avoids claiming startup slots were
polled. The final Hot slot has two seconds before the configured stop. Nothing
extends a window or resets a budget while a password is typed. If typing or
review consumes the launch allowance, the trial refuses before any provider
process starts. The two public downloads occur in the separate preparation
command, before the private password prompt. SDK token refresh may use the
normal shared token database.

The live commands expose no synthetic mode, arbitrary command, forced symbol,
fabricated halt, production-journal argument, widened limits or shifted clock.
The normal one-symbol Nasdaq LUDP/M admission and stabilization rules apply.
The local proposed full-day policy stays sealed; this approval covers only
the shorter invocation, not adoption of daily operating limits or activation
of production Hot.

## Run now, with the market closed

Extract the ZIP once into the existing market-data `output` directory. In
sea-green, run only the offline verifier:

```cmd
call "C:\Users\danla\Documents\github\mb_market_data\output\@@PACKET@@\75_verify_market_open_daily_check.cmd"
```

It runs 48 focused checks in about one minute. The short owned-process proof
executes the fixed public dispatcher with trusted offline SDK/feed/dependency
and constant shifted-clock substitutions. It authenticates two roles, publishes
synthetic admission, records two native Hot samples, then checks owned cleanup,
audit and matching replays. Early operator stop correctly remains INCOMPLETE
for the full three-capture live trial. The unchanged long pacing, replacement
hold, capacity and historical drills are retained rather than repeated.
The defaults for an ordinary full-day launch remain 9,360 calls / 390 feed
attempts. Local POSIX success does not count as Windows qualification.

## Prepare during the next confirmed regular session

First complete the day's ordinary OV/Focus r1 preparation and normal polling
opening check. Keep healthy production polling running. Use the actual r0 and
Focus r1 proposal paths from that preparation. The Focus path does not exist
until that morning's run; it must not be guessed from yesterday's timestamp.

The following is a command template. Replace `ACTUAL_FOCUS_R1_PATH` with the
saved proposal path. The opening path shown is the already prepared October 30
r0. The command requires a successful Windows75 result in this exact packet:

```cmd
call "C:\Users\danla\Documents\github\mb_market_data\output\@@PACKET@@\76_prepare_market_open_daily_check.cmd" --opening-proposal "C:\Users\danla\Documents\github\mb_market_data\output\daily_universe_production\2026-10-30-from-2026-10-29\opening_hierarchy_r0.json" --focus-proposal "ACTUAL_FOCUS_R1_PATH" --market-open-confirmed --public-source-download-approved
```

It prints a fresh `Prepared trial:` path under this packet's `runs` directory.
Save that exact path. It downloads the current-day directory, copies proposal
bytes, creates only the isolated baseline and records explicit cadence-context
descriptors. Those descriptors are not Uni/Focus collections. It never asks
for a password, starts a daily owner, copies production acquisitions or changes
a production journal. Partial preparation is retained and is never reset.

## Launch after approval of this concrete bounded trial

The live command below is a template; replace `PREPARED_TRIAL_PATH`. It prints
the exact dated collection window, fixed limits and review digest, saves the
complete review, then privately prompts for the encrypted-config password.
Run it in its own CMD window. The weekday 09:30–16:00 ET clock gate is
conservative; `--market-open-confirmed` is the operator's confirmation that
the exchange is actually open. At least 235 seconds must remain before close.

```cmd
call "C:\Users\danla\Documents\github\mb_market_data\output\@@PACKET@@\77_run_market_open_daily_check.cmd" --trial-root "PREPARED_TRIAL_PATH" --ecfg "C:\Users\danla\MBV\secure_schwabdev.ecfg" --market-open-confirmed --provider-trial-approved
```

There is one normal three-minute collection interval after startup, then the
original bounded cleanup and separate final reporting. Let the command return
to the CMD prompt. Return its report and owner receipt printed in the console.
The runner reports a missing Windows75 prerequisite explicitly before network
or password actions. A launch refusal does not authorize resetting old state
or issuing a new provider run without reviewing its retained evidence.

## Status, stop and report

These commands read or cooperatively stop only the prepared trial. They never
discover/kill another PID or restart a production channel. Substitute the same
exact `PREPARED_TRIAL_PATH`:

```cmd
call "C:\Users\danla\Documents\github\mb_market_data\output\@@PACKET@@\market_open_check.cmd" status --trial-root "PREPARED_TRIAL_PATH"
call "C:\Users\danla\Documents\github\mb_market_data\output\@@PACKET@@\market_open_check.cmd" stop --trial-root "PREPARED_TRIAL_PATH"
```

After owned producers have stopped, a report can be read again without an API
request or password:

```cmd
call "C:\Users\danla\Documents\github\mb_market_data\output\@@PACKET@@\market_open_check.cmd" report --trial-root "PREPARED_TRIAL_PATH"
```

Preserve the entire trial directory and receipts. The owner uses the accepted
process-scope cleanup if cooperation fails. The report requires non-forced,
empty acquisition and reporter scopes, successful internal role cleanup, native
audit and matching replays. A persistent source/credential/provider/evidence
failure remains a failure or incomplete result. No deadline is relaxed to
turn it into a pass. There is no source installation to roll back; stopping
and retaining this isolated invocation is the trial rollback procedure.

## Interpret the result

`daily_path_check_passed` requires the real daily composition to complete its
bounded source CURRENT/history/fresh-CURRENT sequence and safe closeout.
`collection_observed` separately states whether valid Hot acquisitions were
actually recorded. A quiet run can pass the source/authentication/idle path
with zero Hot acquisitions. It does not prove an admission or Hot collection
occurred. A halted symbol's old trade time is not evidence of a dead poller.

Historical trace gaps remain visible. The cutover flag is a historical
observation within this bounded run, not a promise that the feed is still
current when a saved report is later viewed. An early operator stop is
INCOMPLETE for the full trial even if its sampled quotes/audit/replays are good.
The accepted after-hours provider timings and prior Windows71/72 evidence are
retained. This short check does not establish full-day/provider capacity,
adopt the production settings, or approve production Hot activation.

Completion correction: after the last scheduled slot, verified idle progress now
reports schedule_complete until the dated stop. Reaching the call ceiling while
a future slot remains still blocks before another provider call. Focused native
checks cover both cases; the quote ceiling and native acquisition engine are unchanged.
