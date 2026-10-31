# Manual membership controls — first candidate, October 31

This separate development candidate implements manual promotion, lowering an
operator's own request, withdrawing an own request, and explicitly privileged
restrictions through the existing request/policy/publication backend. It adds
persistent feedback rather than changing membership directly.

Monday's approved p85 release, settings, source inventory and approval are
unchanged. No production attachment, installation, credential or provider entry
is exposed by this packet. Its commands operate only on new synthetic fixtures.

## October 31 Windows acceptance and readable preview

Original command89 is Windows-accepted: 54/54 checks and all nine actual Tk phases
passed in 7.953 seconds, with the actual CMD prompt returned. Its report/source
inventory remain preserved. Repeating those checks is unnecessary for the display
duration change.

The separate preview packet p91 runs the same synthetic GUI phases and holds the
completed, refreshed display for 15 seconds with a countdown before closing.
The timer uses Tk callbacks, so the window remains responsive and Close still
works immediately. Only the presentation hold/entry changes; all existing runtime
source files, backend behavior, deadlines, p85 and its approval remain unchanged.

For the new `@@ZIP@@` preview packet, extract separately:

```cmd
powershell -NoProfile -Command "Expand-Archive -LiteralPath 'C:\Users\danla\Downloads\@@ZIP@@' -DestinationPath 'C:\Users\danla\manual91'"
```

Then run only the preview, without repeating command89:

```cmd
call "C:\Users\danla\manual91\p91\91_preview_manual_membership_15_seconds.cmd"
```

The sections below retain the original candidate verification/interactive-preview
procedure for reference. The p91 layout uses `p91` in place of `p89`.

## Development follow-up — steady buttons

The reported button pulsing came from disabling and re-enabling edits for every
background refresh. The next candidate retains button state during a normal read
and updates a widget's state only when that state actually changes. Initial,
failed/delayed reads, active submissions and privileged controls still enforce
their original availability rules. A deliberate click during a routine read is
captured once, dispatched only after a successful fresh read, and cancelled if
that read fails or the window closes. No duplicate action is queued.

The 18 affected UI checks pass locally, including steady state/no repaint, one
queued click, failed-read cancellation and delayed-read/close handling. Rebuilt
full verification now contains 58 checks; original Windows p89 acceptance remains
54/54 for its exact source. This follow-up is retained for the next development
candidate; no separate Windows preview repeat is requested just for this report.

## Windows qualification

In `prod-prep` with `sea-green` active, extract to a short separate path:

```cmd
powershell -NoProfile -Command "Expand-Archive -LiteralPath 'C:\Users\danla\Downloads\@@ZIP@@' -DestinationPath 'C:\Users\danla\manual89'"
```

Then run this command alone:

```cmd
call "C:\Users\danla\manual89\p89\89_verify_manual_membership.cmd"
```

Allow about 30 seconds for a rebuilt verifier. It runs 58 focused checks, a synthetic native-journal
proof and an actual Tk window that exercises nine phases and closes itself.
No password, API access, production journal read/write or poller/controller
operation occurs. Paste the final JSON and returned CMD prompt.

An optional interactive synthetic preview is available afterward:

```cmd
call "C:\Users\danla\manual89\p89\90_preview_manual_membership.cmd"
```

The preview uses MSFT, AAPL and SPY. MSFT has simulated Nasdaq demand. Its
publisher operates only on the preview's synthetic journal; no quote collector
is started. Close the window to finish. Files remain under this packet's `runs`
directory for inspection. The synthetic session clock starts on a future date;
the preview advances it with elapsed time. Qualification deliberately advances
the logical clock through the actual 60/120-second demotion policy boundary.

## Controls and feedback

- **Request Focus / Request Hot:** create an operator-owned request until the
  bound publication close. A request for Focus alone does not withdraw an older
  Hot request.
- **Demote own to Focus / Uni:** select an own request. Hot-to-Focus first saves
  replacement Focus demand, then withdraws that exact own Hot request. A retry
  after interruption retains both command IDs and never creates duplicate demand.
  Demotion to Uni withdraws the own higher request; opening Uni remains intact.
- **Withdraw selected own request:** cancels only the selected operator-owned
  demand. Nasdaq and other sources keep their own requests.
- **Limit symbol to Focus / Uni:** an explicitly privileged cap that overrides
  ordinary demand, using the existing restriction policy. Unprivileged bindings
  cannot invoke it. **Clear selected restriction** names its exact restriction
  ID, so a stale selection cannot clear a newer restriction.
- Each durable action shows its requested group, receipt status, actual effective
  group and pending publication separately. Details retain other-source demand,
  restrictions and stabilization holds. Acceptance alone never means effective.
- A failed read retains last-verified feedback and disables edits. A saved command
  with an uncertain reply can be retried with its original ID. Closing the controls
  does not cancel requests or stop a publisher/collector.

## Boundaries and next integration

The first candidate supports promotions within the verified opening Uni.
Outside-Uni manual promotions are durably blocked as requiring identity
confirmation. Catalog membership alone is not substituted for broker identity.
The attaching application supplies one trusted local actor and explicit privilege;
this is not OS or network authentication and the GUI cannot choose a producer ID.

The adapter requires an already initialized, explicitly manual-enabled request
session. The frozen p85 request policy permits only its Nasdaq source, so the
adapter refuses attachment rather than enabling manual mutations there. A later
reviewed daily composition must connect the manual source, shared identity/call
budgets for outside-Uni admission, publisher/controller integration and launch
binding. This packet does not claim that production integration is complete.

The accepted Hot provider, paced-source, recovery and full-history proofs are
retained. They are not repeated by these controls-only checks.
