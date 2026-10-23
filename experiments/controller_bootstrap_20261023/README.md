# Fresh authenticated controller bootstrap — command 41

This package qualifies the first implementation slice of the defined combined
Nasdaq/Coordinator/authenticated Hot recovery experiment. Run only:

```bat
call "FULL-EXTRACTED-FOLDER\41_verify_controller_bootstrap.cmd"
```

The source guard runs before tests. All checks are offline, with synthetic
encrypted configuration, metadata-only token fixtures and a synthetic SDK.
There is no real password prompt, installed-client authentication, feed request,
quote call, production journal/process access or live launcher in this package.
Use the existing sea-green environment. Nothing is installed or upgraded.

The implementation validates public inputs and reviewed dependency bindings,
accepts credentials/horizons, and only then claims a new experimental directory,
creates the native schema-v2 journal and future-effective empty-Hot anchor,
initializes bound request/publication/source ledgers, and registers the first
native Hot polling run. It retains a RAM-only manual-session secret bound to
the actual authenticated worker configuration. No acquisition/worker is started.

Failed authentication leaves the target experiment uncreated. An interruption
after creation preserves partial artifacts; another fresh invocation refuses
to adopt/reset them. Input hashes and the preparation window are rechecked
after authentication and before durable stages. A private-pipe entry supplies
independent credential/bootstrap deadlines, redacted fixed-schema receipts and
owned-process qualification drills. Its one-shot qualification entry closes
the client; the eventual runtime controller will use the session-building API.

The tests exercise actual pinned mb_tools encrypted-config/status/client-factory
interfaces with a synthetic SDK, native initial journal/run ordering and replay,
changed inputs/dependencies, authorization refusal, deadline/secret handling,
clock/window boundaries, existing targets and interrupted partial creation.
The 16-test initial development failure (incorrect close boundary) is retained
separately and corrected before delivery. Earlier accepted commands retain
their original sources, scopes and verdicts.

Catalog eligibility is explicitly supplied by a trusted caller and bound in the
initial request identity. This slice does not fetch/qualify a live catalog or
perform broker symbol resolution. Runtime loop, owned-worker timing, cumulative
identity lookup budget/one-symbol fence, manual resume, bounded live acquisition
and recovery, Overlay adaptation, broader capacity and production adoption
remain pending. Production Hot remains disabled.

Completion requires the final report and actual return to the CMD prompt.
Paste both. The Windows result is recorded separately from local qualification;
the report's installed/live-authentication flag remains false for this offline
scope. Accepted commands 32/33/35/37/38/39/40 need no unchanged rerun.

## Windows acceptance — October 23

Command 41 is accepted from the complete MasterBot/sea-green Windows console:
53/53 PASS, zero skips/errors/failures, 17.217276599956676 seconds (runner
17.047 seconds), run `20261023T155228Z-afc55817`, followed by the actual CMD
prompt. The reported saved file was not independently uploaded. The supplied
JSON and console are retained in `validation/windows_command41_qualification.json`
and `validation/windows_command41_console.txt`; the separate
`validation/windows_command41_acceptance.json` satisfies the verifier's fixed
`OPERATOR_RESULT_REQUIRED` label without changing that original report.

All 64 bundled repository files and the original archive remain unchanged.
Acceptance updates only documentation and records. No unchanged command-41 or
earlier accepted qualification needs repeating. Runtime supervision, live
catalog/resolution, cumulative identity budget/one-symbol fence, manual resume,
bounded authenticated live recovery and the Overlay adapter remain pending.
