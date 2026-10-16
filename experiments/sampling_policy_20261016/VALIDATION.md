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

## Windows acceptance

**Pending.** The uniquely named review ZIP contains the development source snapshot
and pinned first-proof market-data reference. Run `01_run_sampling_policy.cmd`
once on MasterBot. Expect all 43 tests OK, `Restriction and demotion policy proof:
PASS`, then a clean prompt return. Do not rerun the earlier 30-test acceptance for
this review. Production polling remains independent.
