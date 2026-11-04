# Nasdaq + manual requests + corrected Hot collector

## Priority reset — 2026-11-04

The operator's immediate objective is usable automatic Nasdaq LUDP/M admission
and manual membership requests driving reliable Hot collection. Additional
ordinary Uni/Focus production sessions, closeout-reminder refinement, optional
Pushover, and Overlay work are not prerequisites for this integration work.
Production Uni is left alone; Focus remains stopped at the operator's direction.
The existing November 4 legacy-cadence journal is not a test fixture.

## Reuse the accepted implementation

- Native reliability checkpoint: `53fc9d62155063b3ae2bc5f0bacfd604866241e0`.
- Coordinator runtime checkpoint: `5b04b479164eb01e6d8eb2b142f70bb9dabf629c`.
- Published manual operating checkpoint: `0ee8d733aeda7843462c1260ec8fca1520a9d840`.

GitHub compare confirms the Coordinator reliability base is 22 commits ahead of
that manual checkpoint with no divergence. Manual controls, shared identity,
owned-controller fixtures and p94 operating delivery already exist. No merge
of a separate manual implementation and no replacement runtime are required
for this first proof. Earlier statements that there is no operating Hot launcher
were inaccurate: the low-level native API is not itself the p85/p94 launcher.
The corrected combined release still requires qualification and activation review.

## This increment

No runtime modules or policy settings are changed. Two new integration tests
combine outside-opening-Uni manual X000 and synthetic Nasdaq X001 admission,
shared identity authorization, atomic membership publication and the actual
native five-minute-period collector. They test the healthy tail-window path,
and inject final local deadline expiration into that same mixed composition.
The latter restarts the collector and must retain the missing slot, avoid a
second dispatch for that slot, collect only future slots and preserve the raw
native audit FAIL despite matching replays. Logical time injection is not an
elapsed-time throughput or real-provider-capacity claim.

The runner also selects six existing tests against the corrected native pair:
actual owned-controller/worker collection for both outside-Uni sources; a
20-manual/20-Nasdaq capacity burst with native collection; the last-capacity-slot
race; existing own-request demotion/restriction behavior; one identity proof
shared across both sources with own withdrawal preserving Nasdaq demand; and
retained-state controller resume with old controls fenced. No new automatic
suppression policy is introduced. Ordinary demotion remains the accepted scope.

## One Windows verification block

Use the existing isolated reliability checkouts and `sea-green`, not the
closeout experiment or a production checkout. The runner verifies actual
Git/import identities, refuses changed tracked source and untracked Python
under source/test/probe folders, and will not silently use an installed native
package instead of the pinned native checkout.

```cmd
conda activate sea-green
set "MB_NATIVE_CHECKOUT=C:\Users\danla\hot_reliability_20261103\mb_market_data"
set "MB_COORD_CHECKOUT=C:\Users\danla\hot_reliability_20261103\mb_watchlist_coordinator"
git -C "%MB_COORD_CHECKOUT%" pull --ff-only && call "%MB_COORD_CHECKOUT%\experiments\hot_manual_integration_20261104\verify.cmd"
```

No real password, live Nasdaq transport, real Schwab quote request, production
journal, Hot activation, repository installation or scheduled task is requested.
The owned-process fixtures use synthetic credentials/SDK responses only.
Each run retains `console.txt`, `result.json`, the new scenarios' real synthetic
journals/sidecars and owned-controller proof evidence under a fresh timestamped
`output/hmi/` directory in the isolated Coordinator (compact-windows-v2 layout).
Full test selectors and the proof-directory mapping remain in `result.json`.
Run-level PASS means eight test cases passed without failures, errors or skips;
it does not change the deliberate missing-slot test's native audit FAIL.

## Validation status at initial publication

New Python syntax and seven LOCAL VERIFIER-ONLY contract tests passed. Those
checks cover Git clean/dirty and untracked-Python refusal, receipt isolation,
console retention, unique selector declarations and syntax. They are **not**
execution of the actual integration fixtures.

Direct Git checkout/archive access in this assistant runtime was unavailable;
repository inspection and publication used the GitHub connector. No local
end-to-end execution or Windows result was claimed at initial publication.

## November 4 Windows path failure and correction

Checkpoint `585220245fc9195d6456475292d1f3381fb2f7fa` failed during the first
fixture's setup, before either mixed-source acquisition test body ran.
Windows returned `WinError 206` while creating the journal directory. The
operator's directory path was 252 characters; the proposed database path
was 271 characters. The retained failed run is
`output/hot_manual_integration_20261104/20261104T155229681584Z-65a2486c/`.
Its result remains FAIL: one test entered, one setup error. No runtime or
provider conclusion follows from that failed setup.

The correction changes only verifier/test evidence paths and documentation:
`output/hmi/<UTC-second-stamp>-<random-id>/p/m/ok`, `p/m/gap`, and `p/o`.
The full test names remain unchanged. Production journal directory names,
native sidecars, all test assertions, eight selectors, source pins, budgets,
and timing limits remain unchanged. New runs cannot overwrite the failed run.
The Windows verifier checks a conservative path budget before creating its
output or starting a fixture. No Windows long-path policy, registry setting,
production checkout, environment installation, or runtime module is modified.

Seven local layout checks passed, including reconstruction of the operator's
252-character failing path, compact native/sidecar paths, overly long path
refusal, isolated-output containment, distinct run IDs, full selector/alias
mapping and no-write layout checks. Python syntax passed; AST comparison
confirmed that only the fixture-root assignment changed in the integration
class. These are **not** Windows filesystem execution or Hot integration
results. The actual eight-case combined qualification remains **PENDING**.

The layout-only regression can be run independently with:

```cmd
python -B experiments\hot_manual_integration_20261104\test_path_layout.py
```

## Remaining operating gate

After this bounded combined run, use its retained evidence to decide the next
changed-path check: simultaneous source/manual load with retained history and
actual owned-process deadlines, followed by one reviewable corrected
manual-enabled operating candidate. Reuse earlier accepted qualifications within
their scopes; do not repeat unchanged long profiles. Any live trial or production
activation needs concrete release/settings/date approval. Original 750 ms,
40-symbol, budget and cleanup limits remain unchanged. Frozen p85 and its
November 2 failure remain intact; do not reset its terminal or recycle budgets.
