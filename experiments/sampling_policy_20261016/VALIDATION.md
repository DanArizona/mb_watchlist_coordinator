# October 16 restriction and demotion validation

## Local verification

- Python 3.12.14, Linux: full repository suite **195 tests and 14 subtests PASS**.
- New noninteractive runner: **43 tests PASS** (35 policy/store tests and 8 journal
  integration tests), followed by the separate retained proof PASS.
- Compatibility runner: all **30** previously accepted source-owned request tests
  and its retained proof PASS with policy omitted. This is a local compatibility
  check of the new optional-policy code; it does not replace the original Windows
  acceptance of implementation 4c4e976.
- Retained new proof: 21 receipts, 22 complete hierarchy revisions, zero acquisitions;
  real schema-v2 audit PASS, two replays identical, publication retry idempotent.
- Injected channel-write failure rolls back a whole hierarchy while retaining the
  durable request. Restart reconstructs original timers and restriction expiry.
- Focused checks include exact grace/residence boundaries, request renewal, nested
  Hot retention, replacement expiry without resurrection, stale/unauthorized
  controls, retained demand under caps, current-demand clear/expiry and reentry.
- Every owned SQLite connection closes explicitly. The first accepted frozen proof
  is unchanged byte for byte. Generated SQLite files and run directories are ignored.

The fixture explicitly uses a synthetic policy clock and requires all policy
settings: 60-second grace, 120-second residence and immediate privileged caps under
proof-super-user. These are test values, not accepted production defaults.

The retained local examples are in `validation/`. Their absolute paths identify
the local host. New runs produce their own timestamps and hashes.

- Request replay SHA-256: `e71adf098b6242beb184d51e02eec7a4cffcf72cf94fe8dc2898c52701295d3c`.
- Journal replay SHA-256: `5f7f636ca1ddb4cd34d677ae3d4c5ac056bba313fbdaaa964627cbd17501e639`.

## MasterBot Windows acceptance — COMPLETE

User-supplied CMD output from `coordinator_policy_20261016_162859_5d4455.zip`
confirms all **43 tests PASS in 1.521 seconds**, followed by
`Restriction and demotion policy proof: PASS` and a clean return to the prompt.
The retained proof verifies fast promotion, delayed ordinary demotion, one
restriction authority, rejected foreign/stale controls, current-demand clear/expiry,
no superseded-cap revival, restart-preserved timers/deadlines and fresh reentry
residence. Journal audit PASS; two replays identical; retry idempotent.
There are 21 receipts, 22 hierarchy revisions and zero market acquisitions.

- Request replay SHA-256: `db6a50172ebc8ba5637d80cb99fcb28dd7af84fb638636fad22c78ac8591f462`.
- Journal replay SHA-256: `1aaba6a8e4ee1a5033c9d5084e3f0f23a89afe24afb6ec22ee3c44b66f676683`.
- On-host report directory:
  `C:/Users/danla/Documents/github/mb_market_data/output/coordinator_policy_20261016_162859_5d4455/experiments/sampling_policy_20261016/runs/20261016T223125Z-c1a0ccb7`.

The structured evidence is retained in `validation/masterbot_acceptance_20261016.json`.
Detailed reports and SQLite journals remain on MasterBot; acceptance here is based
on the user-supplied console output. This documentation-only update changes no
implementation, test, manifest or accepted ZIP and requires no test rerun.

The synthetic clock, 60-second grace, 120-second residence and immediate-cap
selection remain explicit test configuration. Windows acceptance establishes the
implementation's scoped behavior, not production settings, authority authentication,
live scheduling/outbox, Nasdaq integration, Hot acquisition or live latency.
Production polling closeout remains separate.
