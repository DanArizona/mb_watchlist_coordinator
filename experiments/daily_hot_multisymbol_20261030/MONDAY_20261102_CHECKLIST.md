# Monday November 2 startup checklist

The p85 multi-40 release and Monday settings are approved, including retained-state
manual resume. See [approval](ACTIVATION_APPROVAL_20261102.json) and
[reviewed scope](ACTIVATION_REVIEW_20261102.md). The operation has not started.
Use MasterBot, sea-green, and the existing p85 directory. Times below are Eastern
Standard Time (`-05:00`): opening09:30 is14:30UTC; closing16:00 is21:00UTC.

## Around 08:50 ET: ordinary preparation

Check the installed repository state and credential status as usual. The accepted
refresh renewal covers Monday; retain the normal startup horizon checks.

```cmd
mb-schwab-auth --status
```

The published Monday r0 is already accepted:584Uni/0Focus/0Hot. Use its existing
file; no new r0 build/publication is required merely to start the day.

## At or after 09:00 ET: API overnight volume and Focus

Start overnight acquisition promptly to leave time for r1 and Hot preparation.
Run this single command and answer its encrypted-config prompt:

```cmd
python "C:\Users\danla\Documents\github\mb_market_data\probes\acquire_api_overnight_volume.py" --opening-proposal "C:\Users\danla\Documents\github\mb_market_data\output\daily_universe_production\2026-11-02-from-2026-10-30\opening_hierarchy_r0.json" --request-interval 0.5 --ecfg "C:\Users\danla\MBV\secure_schwabdev.ecfg"
```

Use the actual printed manifest to build the usual40-symbol OV Focus. Publish
its actual r1 into the Monday production journal, then run opening audit/replay.
The generated manifest/r1 paths cannot be filled in before this work occurs.
Their exact binding is already covered by the approved scope.

## Before 09:20 ET: independent pollers and Hot preparation

1. Start ordinary Uni, Focus and Health in their independent windows, using
   interleaved-v1 and Monday's09:30–16:00EST window. Check startup readiness.
2. Obtain the Hot catalog for the actual Monday ET date. This entry has its
   original two-retrieval ceiling and reuses an already complete bound catalog:

```cmd
call "C:\Users\danla\hot85\p85\hot_daily.cmd" catalog --session-date 2026-11-02
```

3. Use the actual published Monday r0/r1, production journal, credential path and
   catalog with the existing `hot_daily.cmd prepare` entry. We will supply the
   exact preparation command from Monday's printed paths. It creates a dated
   review and bound START_HOT/STATUS/MEMBERSHIP/STOP_HOT/ROLLBACK_HOT commands.
4. Check the returned summary matches the approved date, source inventory,
   multi-40 policy, membership bounds and original budgets. Use its exact
   `start_command_after_approval`; the new digest is a technical binding within
   the approval already granted.

## Target 09:20 ET: approved Hot startup

Run the generated start command in its own Hot CMD. Enter the password promptly:
**it must finish before09:29ET**. Startup occurs before the market opens; the
combined committed-slot opening check follows after09:30. A fresh after-open
start or past-slot catch-up is outside this release's supported path.

Open the generated MEMBERSHIP command. The display shows all current Hot members
and current Focus/Uni additions beyond pinned opening r1. Use STATUS to inspect
source, worker and cleanup state. A quiet or ineligible feed can leave Hot empty.

## After 09:30 ET: opening and continued observation

Confirm scheduled Uni/Focus outcomes, Hot worker health, source reconciliation,
and Hot acquisitions when membership is nonempty. Check the saved incidents and
persistent membership display. Keep healthy independent pollers running if the
Hot operation stops. The source's known history gaps remain visible.

For manual resume, inspect the reason/report, confirm empty old scope and released
owners, prepare a resume from the previous actual review, then use the newly
printed bound start command. Enter the password again. The collector receives a
fresh minimum15-second hold; original budgets and the cumulative3-start ceiling
remain. This approved same-session resume needs no additional chat permission.

## At close or an earlier operator stop

Inspect Hot cleanup and final native coverage, full Hot value integrity and
native event-order checks. Complete the ordinary Uni/Focus closeout. Retain
membership, journals, source/request evidence and period ledgers. Stop/rollback
addresses only the bound Hot owned scope. Actual full-session/live-provider
qualification will be assessed from the observed results.
