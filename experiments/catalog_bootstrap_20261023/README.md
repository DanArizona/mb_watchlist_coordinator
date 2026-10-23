# Authenticated catalog-bound startup — command 43

This implements the startup integration checkpoint after Windows-accepted
commands 41 and 42. Run only the offline verifier:

```bat
call "FULL-EXTRACTED-FOLDER\43_verify_catalog_bootstrap.cmd"
```

Use sea-green; nothing is installed or upgraded. No real password, vault,
installed SDK authentication, public feed/directory/broker request or production
journal/process is accessed. All credentials, SDK responses and HTTP scenarios
are synthetic. The source guard runs before tests. Completion requires final
JSON and actual return to the CMD prompt; paste both.

## Implemented startup path

The new explicit `owned_directory` mode validates public inputs and frozen
window before the private password frame. It authenticates once, including
fresh pre/post-constructor credential horizons, before claiming the new
experimental root. Failed credentials create no target or directory work.

It then claims a local owner lease, initializes a separate SQLite directory
ledger, and commits one invocation reservation consuming both source permits
**before** starting acquisition. The accepted two-source catalog driver still
uses at most two owned children, 10 seconds each and the earlier bootstrap
deadline, without retry/fallback. Both permits are conservatively consumed even
if the process dies before either fetch. They are a dispatch ceiling, not a
complete audit asserting two HTTP calls occurred.

Successful raw source bytes and receipts are committed to the ledger before
catalog artifacts are persisted. Catalog identity then binds ordinary request
admission, the initial native journal, Coordinator publication, the identity
gate, and the actual Hot worker configuration. The returned session defaults
to the gated delivery adapter in this mode. The first native `poll_run` is
registered only after all these bindings. Hot begins empty; no RSS, identity
quote, collector process or runtime loop starts during bootstrap.

Interrupted/failed reservations remain charged and cannot be retried or reset
under the same experiment identity. Captured bytes can be verified and
reconstructed through a read-only API without another retrieval. A fresh
invocation rejects any existing/partial target before reading another password
frame. This is preparation for full manual resume, not its implementation.
Missing/corrupt evidence is blocked and retained rather than adopted/reset.

## Compatibility and qualification

Two accepted shared source files are extended: `controller_bootstrap.py` and
`bootstrap_entry.py`. Default caller-supplied v1 public configuration identity
and receipt shape are preserved. The new v2 receipt explicitly separates the
preflight identity, catalog-bound identity and reserved directory permits.
Original accepted commits and ZIPs remain intact; their pinned verdicts stand.
No unchanged installed-client or historical live trial is repeated.

Focused checks include legacy credential/bootstrap and catalog/identity/native
regressions, failed auth before directory/native creation, malformed inputs,
bounded owned synthetic HTTP, artifact/ledger tampering, conservative unknown
budgets, a catalog with 7,000 additional synthetic identities, and native audit
with two matching replays. Actual owned-process exits cover reservation,
captured bytes, catalog binding and initial native registration. Independent
credential/bootstrap/close deadlines and redaction are exercised using pinned
public mb_tools interfaces and fabricated encrypted configuration/token metadata.
Large-catalog identity consistency is not a provider/full-day capacity claim.

Current-host focused qualification passes 288/288 checks in
37.30795769899987 seconds (runner 37.210 seconds), zero skips, failures or
errors. The earlier development run with one test-fixture import error is
retained separately; its correction did not change runtime behavior.
Source-pinned extraction and Windows operator acceptance are recorded
separately. Command 43 Windows acceptance is complete; see the operator record below.

The acquisition driver is an explicit trusted API/test seam; this package has
no operator live-start command or implicit network authorization. The source
pin and ordinary configuration cannot select a synthetic/live driver by input
data. Production Hot remains disabled.

Next are prepared-client runtime supervision, the original 3-second worker
startup/staleness and separate 8-second credential timing boundary, full manual
controller resume, and separately invoked bounded live acquisition/recovery.
The 60-second bootstrap and frozen T0/Tstop are not extended. Overlay follows
backend qualification; production adoption and broader capacity remain pending.

## Delivered qualification

The immutable 237574-byte, 83-file archive is
`catalog_bootstrap_20261023_191459_210b73.zip`, SHA-256
`c517271807c6190827fdfd6485f5f191132e48b0d2e85aa3d4f286926aa135b7`.
It pins [source 46e96d7](https://github.com/DanArizona/mb_watchlist_coordinator/commit/46e96d7951b881b1cc6f07c37de2941aecdd5ad1),
tree `06a11d44333e01e983a0898f443bd69227f04cf6`. Source-pinned extraction in a
path containing spaces passes all 288 checks in 37.77484418899985 seconds
(runner 37.575 seconds), with no skips, errors or failures. All 79 mapped
repository files match; altered/extra-source probes both return 70 before
tests and restoration matches the complete inventory. Original command-41/42
archives retain their hashes. Command 43 Windows operator acceptance is now
complete. The reports and source-guard evidence are in `validation/`; this
delivery update changes documentation/records only, not the delivered archive.

## MasterBot Windows acceptance — October 23

Command 43 completes with 288/288 PASS in 51.14706789993215 seconds
(runner 50.907 seconds), zero skips, failures or errors, run
`20261023T193036Z-851ae3c3`, followed by the actual sea-green CMD prompt.
The complete operator console and JSON supply acceptance; the saved report
file was not independently uploaded. Its fixed `OPERATOR_RESULT_REQUIRED`
label is retained verbatim and satisfied by the separate
`validation/windows_command43_acceptance.json` record. The qualification JSON
and console transcription are alongside it.

The original ZIP and all 79 mapped repository files remain byte-identical.
Acceptance changes documentation and validation records only; no unchanged
command-43 or earlier accepted rerun is needed. Synthetic credentials/SDK/HTTP
are qualified here. Installed startup retains the separate command-40 scope;
running collector supervision, full manual controller resume, live recovery
and broader capacity remain pending. Next is prepared-client runtime
supervision with the original 3s/8s gates, then full manual controller resume.
