# Human-started authenticated Hot worker startup

Command 38 qualifies the new startup and private credential handoff using
synthetic credentials, a synthetic SDK and actual owned child processes. It
requires no password, API access, open market or production journal. It does
not launch an authenticated market trial. Commands 32/33/35/37 keep their
accepted source-pinned results; their unchanged packages need no rerun.

## Credential boundary

The public mb_tools credential contract remains authoritative. A human starts
one controller session and supplies the encrypted-config password through a
hidden prompt. `SessionPassword` holds it in RAM and sends a bounded frame over
an anonymous stdin pipe only when starting an explicitly owned worker. Each
frame binds the password to that child's generation token. Public jobs bind
the complete ordinary configuration by SHA-256; they contain no password or
password hash. No password file, environment variable, command argument or
new OS credential store is introduced. Buffer clearing is best effort and is
not a claim of guaranteed Python memory erasure.

Owned child restarts can reuse that live controller session. After the
controller exits or its session secret is closed, a new launch requires the
human prompt again. Public worker files cannot restore the password. Complete
unattended restart after reboot/controller loss remains outside this increment
and requires the credential contract to be addressed separately.

The authenticated entry accepts only an explicit absolute `.ecfg` path and
uses installed mb_tools secure-config/status/client interfaces at runtime.
Before constructing the client, and again using a fresh status read after
construction, it requires refresh validity through the acquisition stop plus
the existing mb_tools 75m30s polling margin. Request timeout is at most 3s;
the independent child startup watchdog is at most 8s. A controller integrating
this mode should allow the child startup bound plus scheduling overhead within
the existing maximum 10s worker startup gate. No existing default gate is raised.

Interactive authorization is rejected; browser opening is disabled through the
shared factory. SDK output is discarded in the worker, and retained diagnostics
use fixed status codes rather than exception text, HTTP error bodies or callback
URLs. A constructor hang or missing private frame is tested against the child
watchdog without parent health checks. An authorization failure, transport error
or decode failure halts further quote dispatch by that client.

## Native collector integration

This is an opt-in v2 worker profile. The existing v1 profile and default lazy
client path retain their identities. The new entry first validates the current
job, configuration fence and existing native acquisition evidence, then prepares
credentials before registering its own new native polling run or recovering
saved acquisitions. It closes the client on a stop or failed post-startup check.
The journal and immutable collector manifest must already exist as isolated
experimental state; this increment does not provide a complete fresh-experiment
controller or credential-gated creation procedure.

On restart, saved assembled responses still commit without another quote
request. Unknown dispatches remain unknown and consume the existing durable
budget. The original 750ms dispatch gate is checked again after a lazy client
factory returns. Budgets, roster limits, generation fencing, fixed window,
future-only resume and the experimental interleaved Hot grid remain enforced.
Healthy existing workers do not need a new password frame, and closing a session
secret does not terminate them. New authentication startup failures create only
non-secret worker/status diagnostics, not a new native polling-run registration.

## Offline verification and reference dependency

Command `38_verify_authenticated_startup.cmd` is accepted on MasterBot Windows:
529/529 PASS in 82.49765909998678s, zero skips/errors/failures and actual CMD
prompt return. No unchanged repeat is needed. The launcher verifies every bundled source hash before running tests.
The verifier and all fixture children deny network. Tests create and remove
only temporary synthetic encrypted configurations and metadata-only SQLite
token fixtures, with explicit connection closure.

The reference mb_tools source is copied byte-for-byte from public commit
`abdceb1be988b7ee893b0bed725b90454ddf4f71`; `reference_mb_tools/PROVENANCE.json`
records the source hashes. Its extra distribution metadata is labeled
`0.0.0+offline.reference` solely so the uninstalled reference can be imported.
The verifier explicitly selects this reference and replaces Schwabdev with a
synthetic module. It does not install or modify mb_tools, inspect the operator's
vault/token database, or establish compatibility with the installed SDK version.
The real reference encryptor, loader, token-metadata reader and client factory
are exercised with fabricated inputs. The fake SDK deliberately emits password
and authorization-URL canaries through Python output and raw file descriptors;
tests scan all retained runtime artifacts for those values.

## Status codes and next boundary

| Code | Operator action for a later authenticated launcher |
| --- | --- |
| `secret_handoff_invalid` | Restore the exact job/configuration pair and start a fresh manual session. |
| `credentials_unavailable` | Supply the password in the controller's hidden prompt. |
| `credential_horizon` | Check credentials with the established explicit auth/status procedure before restarting. |
| `authorization_required` | Complete the established manual authorization procedure separately. |
| `startup_deadline_ended` | Inspect the safe status and process exit; do not widen gates automatically. |
| `startup_failed` | Check the explicit encrypted-config path/password and installed dependencies without pasting secret values. |
| `provider_failed` / `provider_decode_failed` | Retain evidence and investigate the provider failure before another bounded run. |
| `window_ended` | Choose a new explicit bounded window; never catch up past quote slots. |

Windows acceptance of the delivered command-38 bytes is complete. Next check the
actual installed SDK and human-started bootstrap in a separate bounded isolated
procedure, followed by paced live HTTP and market-hours interruption/recovery.
No claim is made for live authentication, whole-machine recovery, complete
historical quote restoration, long-history/mixed-source/provider capacity or
production adoption. Production main, Uni/Focus cadence and Hot-disabled policy
are unchanged. Earlier failed command-34/36 and stress/cloud records remain.


## Completed Windows acceptance — command 38

The completed MasterBot/sea-green operator console for run
`20261023T104346Z-51ddb6c3` reports all 529 tests PASS in
82.49765909998678s, zero skipped tests/errors/failures, network denied,
production access false and an actual CMD prompt return. The saved JSON file
was not independently uploaded; the supplied completed console supports this
acceptance. Its fixed `offline_current_host` environment label describes the
verifier's current host and does not negate the established Windows context.

Qualified implementation remains Coordinator
`5601d2dd8671e0bdbd3d5a0ab0ef62f8c5e34545`. All 85 bundled repository
runtime/test/reference/verifier files match the delivered source inventory;
the original ZIP, launcher and inventory are unchanged. This acceptance changes
only documentation and validation records. Commands 32/33/35/37/38 need no
unchanged rerun. Original command-34/36 and stress/cloud verdicts are retained.
The credential contract, actual installed SDK authentication, fresh-controller
manual prompt requirement and all live/production boundaries remain as above.
