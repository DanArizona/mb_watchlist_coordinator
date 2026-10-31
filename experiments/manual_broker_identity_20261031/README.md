# Manual outside-Uni broker identity — separate development candidate

Step 2 adds an explicit `manual-identity-40-v1` profile to the accepted combined
Nasdaq/manual composition. The approved p85 and accepted p92 packets, settings,
source inventories and verdicts stay frozen. This packet generates no production
start command and performs no installation or activation.

## Behavior

- Manual Focus/Hot promotion within verified opening Uni still needs no broker
  lookup. Other symbols must be in the retained session catalog and receive an
  exact broker `EQUITY`/`COE` identity confirmation before normal admission.
  Publication supplies the nested Uni/Focus/Hot membership through the original
  service; the GUI never publishes membership or calls a provider.
- Outside-Uni submissions are durable and visibly pending. The existing owned
  controller handles their identity queue alongside real Nasdaq source commands.
  Both sources share the original 120-call identity budget, three calls per
  symbol, two-second spacing and 40 distinct authorized symbols. Successful
  exact-symbol evidence is reused across sources without another broker call.
- The common request boundary requires a retained identity approval reference
  for outside-Uni manual demand. Catalog presence alone cannot admit it. The
  first approval reference is stable across lost manual receipts and retries;
  later approvals cannot turn an earlier rejected request into an accepted one,
  even when a logical fixture clock has not advanced. Missing/corrupt proof
  fails closed. Full gate reads still verify source-command provenance.
- A pending own request can be withdrawn before lookup with no dispatch. If a
  lookup is already in flight, its charged result remains retained, but the
  canceled demand is not admitted. Demotion selects an already admitted own
  higher request; to cancel an unadmitted request, use withdrawal. Withdrawal
  preserves Nasdaq demand for the same symbol. Original restrictions and
  stabilization behavior remain.
- Every broker dispatch is reserved durably first. An unknown outcome is not
  retried, including under a new command for the same symbol. An explicit new
  request following an unconfirmed result remains subject to the shared
  per-symbol/session budgets. Provider authorization/rate-limit stops latch the
  same controller-wide stop. Saved state, charges and proofs survive reopen.
- The two sources share the same nonrecycling allowance of 40 distinct Hot
  symbols, 40 Focus additions and 40 outside-Uni additions. Withdrawal or
  restriction does not free a session slot. A full allowance can refuse a
  manual submission before spending another identity call.
- Original collection cadence, 0.75-second dispatch-lateness bound, 300-second
  periods, three-worker-start limit and 3/8/15/10/60-second progress/authentication/
  replacement/cleanup/reporting deadlines remain. The GUI stays pinned to the
  active original controller/configuration and cannot reset/rebind a session.

## Windows qualification

Download `@@ZIP@@` and extract in the sea-green CMD window:

```cmd
powershell -NoProfile -Command "Expand-Archive -LiteralPath 'C:\Users\danla\Downloads\@@ZIP@@' -DestinationPath 'C:\Users\danla\manual93'"
```

Run separately:

```cmd
call "C:\Users\danla\manual93\p93\93_verify_manual_broker_identity.cmd"
```

Allow about 90 seconds. There are 71 focused checks, including an actual owned
controller/identity child/collector/reporter proof, a forced 20-manual/20-Nasdaq
admission burst plus overflow, two native 40-symbol collection cycles with the
original lateness gate using actual elapsed time, native content/audit/replay checks and affected
UI/admission regressions. A synthetic Tk preview shows pending outside-Uni
requests, withdrawal before lookup, broker-confirmed effective membership,
Nasdaq/manual interaction, read failure/recovery and a 15-second completed hold.

All credentials, SDK responses, source captures and journals are synthetic.
Network is denied in the verifier and owned fixture children. No vault or
actual provider/production access occurs. Paste the final JSON and actual
returned CMD prompt. Accepted long history/feed/recovery/provider drills are
not repeated. Real-provider/full-day capacity is not newly qualified.

## Next

After Windows acceptance, prepare the concrete manual-enabled operating delivery,
commands, status/stop/resume workflow and release review. Monday's approved p85
remains the original Nasdaq-only release until a separately reviewed manual
release is ready and approved. The read-only Overlay adapter follows.
