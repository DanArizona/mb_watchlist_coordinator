# Read-only daily Overlay adapter — first Windows candidate

This side-by-side delivery connects saved daily Hot records to the existing
Observation Overlay chart. It supports the approved p85 Nasdaq-only layout and
the accepted p94 Nasdaq/manual layout. It does not install code, change either
packet, change membership, start/restart a collector or access credentials/API.
Monday's p85 release, settings and activation approval remain unchanged.

## November 1 Windows result

Windows96 is ACCEPTED97/97, zero failures/errors/skips,9.356-second tests and
9.625-second total. Exact source/inventory match the frozen1cd53fe delivery.
The operator supplied the complete console/final JSON and returned CMD prompt;
original Windows files were not independently accessed. See WINDOWS_ACCEPTANCE.json.

The actual Windows browser execution served assets/Plotly JS and repeated HTTP200
refreshes, emitted all five preview phases, remained open after completion and
returned to CMD. See WINDOWS_PREVIEW_OBSERVATION.json. This establishes reported
execution, not independent visual acceptance: operator observations of symbol/
chart appearance and read-failure retention are still pending. No qualification
or preview rerun is requested solely to record these results. Source publication
continues to await explicit p96 approval after the automatic review block.

## Windows qualification

Use the existing sea-green environment. Dash and Plotly are the existing Overlay
dependencies; this packet performs no dependency installation. Extract the short
package path:

```cmd
powershell -NoProfile -Command "Expand-Archive -LiteralPath 'C:\Users\danla\Downloads\@@ZIP@@' -DestinationPath 'C:\Users\danla\overlay96'"
```

Then run separately:

```cmd
call "C:\Users\danla\overlay96\p96\96_verify_overlay_adapter.cmd"
```

This runs 97 checks: 58 adapter, actual Dash layout/callback transport and CLI
checks, plus 39 existing Overlay regressions. All data, RSS and clocks are
synthetic. Network connections are denied. No GUI opens during qualification;
no old paced/provider/recovery/capacity drill is repeated. Allow roughly 15–30
seconds on Windows. Paste the final JSON and actual returned CMD prompt.

## Inspect the synthetic browser preview

After qualification passes:

```cmd
call "C:\Users\danla\overlay96\p96\97_preview_overlay_adapter.cmd"
```

The browser stays open until **Stop display** or Ctrl+C. It does not close on a
timer. The page and CMD identify SYNTHETIC PREVIEW throughout. Evidence changes
over about 45 seconds, then the final state remains available for inspection:

1. Opening IBM/MSFT membership and saved MSFT candles. Monitor/Chart/Alerts tabs
   use the existing chart, colors, 800-pixel height and point/axis controls.
2. NVDA appears in the complete Hot list and Focus/Uni additions beyond r1.
   Select NVDA in the searchable picker. Its quotes initially appear without a
   candle cache; nothing fetches or fabricates candles.
3. Saved candles and Nasdaq resumption knowledge arrive. The Monitor separates
   event timestamps from when halt, quote-resumption and trade-resumption times
   became known. Future announced times do not extend a line beyond the cutoff.
4. A deliberate synthetic read failure lasts about 16 seconds. The selected
   chart remains visible with LAST VERIFIED membership/health feedback.
5. Reads recover and the saved controller is STOPPED. Its retained membership
   and chart remain visible; this does not claim active collection.

The fixture uses a logical future session/clock. Its shortened real-time scene
changes are visual demonstrations, not another qualification of 60-second live
source pacing. No actual broker, source child or production journal is opened.
Stopping ends this viewer's server/progress thread; it does not control any
production process. A preview-result.json is saved under this invocation's
own runs directory. Early operator stop is allowed; unvisited phases are not
claimed as completed.

## Read an actual dated daily session after qualification

Use the original generated `operating-summary.json` from the dated Hot review.
It contains the actual state_root and journal_path. The adapter pins those
paths and the attached session/r1 binding. It can wait before initialization
without creating the target state. Monday's exact path will come from Monday's
ordinary p85 preparation; no guessed path or fresh after-open launch is needed.

`98_overlay_adapter.cmd` accepts only `view` or `snapshot`. For a live read-only
view, append `view --operating-summary` followed by the quoted full path of that
original summary. Optional arguments are `--symbol`, `--candle-directory`,
`--port` and `--no-browser`. Direct `--state-root` is available instead of the
summary. The listener is fixed to 127.0.0.1; there is no public-bind option.

`snapshot` prints read-only JSON and returns 1 when the native read is unavailable.
It does not import or start a GUI/server. Neither verb has password, activation,
provider, promotion, withdrawal, startup or resume options.

Saved candles are optional existing native Overlay caches named SYMBOL.json in
the explicitly supplied directory. Session/symbol/hash/availability checks are
retained. A missing or invalid cache is visible; quote history still works.
There is no automatic candle acquisition and no project-data migration.

## Read and knowledge contracts

- The accepted session/claim/opening-r1 reader supplies binding checks. A second
  single mode=ro/query_only native transaction supplies every membership,
  selected-symbol quote, cadence and recorded skip used together in the chart.
  Concurrent publications therefore do not mix revisions within that snapshot.
- Membership comes from published, effective native revisions. Future revisions
  do not populate current picker/list membership. Historical demotions remain
  selectable. Quotes appear only after native completion, with their recorded
  scheduled/completed times, status and per-run cadence.
- Only the selected symbol's quote values are read. Native membership/header,
  ordinal, normalized-format and row-count checks run; this is a display
  projection, not the full native acquisition-content audit.
- Source records use the original retained RSS body/hash/pacing/classification
  validator. Daily source claims, journal/request bindings and authority event
  chains are checked. CURRENT/history observations are facts, not new admissions.
  Halt lines require recorded Nasdaq facts; price/quote gaps or security-status
  fields do not infer a halt. Disappearance from a later feed is not resumption.
- Halt, quote-resumption and trade-resumption knowledge times are distinct.
  An announced future resumption can be known now; plotting is clipped to the
  observation cutoff. A later missing field does not retract a known time.
  Known carryover spans are clipped to the selected regular session for drawing.
- A failed native read keeps only that symbol's last verified chart, with a
  visible failure banner. A source-only failure retains verified source facts
  under an explicit LAST VERIFIED source label while native quotes may refresh.
  Saved source/controller progress age and retained membership are separate.
- Only one model refresh can be in flight. Refresh is every five seconds; UI
  controls stay mounted in all tabs and are not rebuilt on each refresh or tab
  change. No leases or write APIs are used.
  SQLite may maintain its normal volatile WAL/SHM reader state; no application
  membership/quote/source record is written by the adapter.

## Scope and remaining integration

The two documented feed-history gaps remain visible. Recorded skipped outcomes
are shown, but **unrecorded scheduled-slot coverage is not independently assessed
by this display**. Keep Uni/Focus/Health running and use the independent native
audit, Hot-content checks and event-order verification for closeout. This viewer
does not replace that monitor/audit or claim OS-owner liveness from saved files.

The new native changes only permit absent candle caches and clip carryover halt
rendering. Acquisition, controller, policy, deadlines, credentials, publication,
ownership and recovery code are unchanged. The original Overlay regressions are
included because these chart paths changed.

Remaining evidence: actual Windows result/returned prompt, browser inspection,
read-only attachment to a dated running session, longer-session refresh behavior
and the remaining candle-producer/Overlay integration. Full-day viewer/provider
capacity and a complete integrated production Overlay are not qualified here.
P94 production activation remains a separate dated release decision.
