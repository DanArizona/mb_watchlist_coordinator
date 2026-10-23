# Installed Schwab client and one-quote startup probe

The accepted command-38 implementation remains unchanged. This increment adds
a separate installed-client check, with an offline qualification command first.
It starts no native polling run and makes no Nasdaq request or membership change.

## Windows sequence

1. Run `39_verify_installed_probe.cmd` in sea-green CMD. This is offline,
   synthetic-only qualification of changed probe/launcher paths and affected
   credential interfaces. No password or API access is required.
2. After PASS, run `40_check_installed_client.cmd "absolute encrypted-config path"`
   from the same package and environment. It first inventories installed
   dependencies without loading the vault. If that check passes, it prompts once
   and makes at most one SPY quote-client invocation. Market hours are not required.
3. Retain each final JSON and actual CMD prompt return. If a guard blocks startup,
   retain its diagnostic result; there is no automatic retry or upgrade.

The launcher verifies its source inventory for both commands. Command 40 also
requires command 39's same-package/interpreter qualification receipt. A new
failed verification revokes an earlier receipt. Packages contain no such receipt
before the operator runs command 39. No unchanged command 38/37/35/33/32 repeat
is requested; this increment has its own changed-path verification.

## Installed dependency gate

The real entry uses installed mb_tools and Schwabdev. It never adds the bundled
reference mb_tools to its import path. Before the password prompt, it reads the
Python executable/version, distribution versions and eight reviewed mb_tools
source files. The same inventory is checked again in the child before credential
loading. It accepts stable Schwabdev 4.x, following the pinned mb_tools optional
dependency range `schwabdev>=4.0.0,<5` in
[pyproject.toml](https://github.com/DanArizona/mb_tools/blob/abdceb1be988b7ee893b0bed725b90454ddf4f71/pyproject.toml).

The eight helper sources must match public mb_tools commit
`abdceb1be988b7ee893b0bed725b90454ddf4f71`. Only CRLF-to-LF checkout conversion
is normalized; raw and canonical hashes are both recorded. Changed/missing
helpers, unsupported SDK versions, or a bundled reference mistaken for an
installation stop before the prompt/provider child. This deliberately makes
unreviewed installed-helper differences visible. The command never changes
packages, source checkouts or credential configuration to make them match.

## Credential and request scope

The human-started controller prompts through the accepted hidden-password
interface. The password travels to one exact owned child through anonymous
stdin, bound to a fresh nonce. Its public configuration is passed separately
in process arguments; no password, decrypted configuration, token or callback
URL is put in arguments, environment, files or reports. Buffers are cleared on
a best-effort basis, without a guaranteed Python memory-erasure claim.

The child uses the accepted pre/post-constructor refresh-horizon checks, with
the existing stop-plus-75m30s margin and noninteractive authorization refusal.
Request timeout is 3s, startup is bounded to 8s, and the parent permits 20s after
child launch plus bounded terminate/kill cleanup. The child also has independent
startup/whole-window watchdogs. Ordinary SDK token refresh may update the existing
shared token database. Explicit manual reauthorization, if needed, remains a
separate established operator procedure. The probe never starts a browser.

Only one SPY quote-client call is permitted. Authentication/refresh HTTP activity
inside the SDK is outside that quote-client count. This is not a complete HTTP
call audit. PASS requires the child to exit successfully after returning HTTP
200 with the requested SPY identity and a finite positive last price. It records
only that proof, safe dependency metadata and fixed status codes. Raw provider
payloads, errors, headers and SDK stdout/stderr are discarded. A private duplicate
of stdout carries only the module's small fixed-schema result to the controller.

Hung startup, quote or close cannot yield overall PASS. On timeout/unreported
exit the reserved budget stays one and the observed dispatch count is unknown;
it is never silently reported as zero. A final verified child receipt may show
zero dispatches when startup stopped before quoting. Interrupting the controller
stops only its exact owned child. No automatic rerun, symbol substitution or
quote-slot catch-up is implemented.

## Qualification and remaining boundary

Command 39 uses fabricated encrypted configurations, metadata-only token SQLite
fixtures, a synthetic SDK and actual owned child processes. Main and fixture
children deny network. Tests cover dependency/version/source gates, Windows
CRLF handling, private handoff, repeated horizon checks, authorization refusal,
safe error/protocol rejection, one-quote limits, independently stopped startup,
hung quote/close, preserved unknown dispatch and qualification receipt guards.
The real installed-client command has no synthetic CLI option. Its offline
tests do not establish real authentication; command 40's operator result does.

Successful command 40 would qualify only the observed installed interfaces,
human-started client construction and one authenticated SPY quote. It provides
no market freshness, native collector, outage/restart, historical completeness,
long-history/mixed-source/soak/provider capacity or production adoption claim.
It can run outside market hours because it measures startup/transport. The later
live HTTP and market-hours recovery procedure remains separate. A fresh
controller still requires the human password prompt; no unattended decryption
store or credential-contract change is introduced. Production journals/processes,
main branches, Uni/Focus cadence and Hot-disabled policy remain unchanged.

The existing command-34/36 and history-stress/cloud failure records retain their
original verdicts. Command 38 remains accepted at its original source pin.
