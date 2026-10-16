# Restrictions and stabilized ordinary demotion

This isolated increment extends the durable source-owned request path. It does
not install a production Coordinator, alter a production journal or start a poller.

## One Windows check

With `sea-green` active, run the repository-root `01_run_sampling_policy.cmd`.
The window is titled COORDINATOR-RESTRICTIONS-DEMOTION. It runs 43 focused tests
and a separate retained publication/replay proof, then returns to the prompt.
Python 3.12+ and America/New_York timezone data are required. No installation,
password, browser or network call is needed. The runner accepts no arguments.
Each run creates fresh journals and reports only under this experiment's `runs/`.

Expected final marker: `Restriction and demotion policy proof: PASS`.

## Explicit proof settings

| Setting | Proof value | Meaning |
| --- | --- | --- |
| Super User identity | proof-super-user | Only this trusted actor can set or clear restrictions |
| Ordinary demotion grace | 60 seconds | Wait after the first recorded absence of demand |
| Minimum residence | 120 seconds | Wait after entry into each group |
| Privileged timing | immediate_cap | An active cap bypasses ordinary retention waits |

These are review fixture settings, not adopted production defaults. `SamplingPolicy`
requires every setting explicitly. The immediate-cap exception is the supported
explicit test selection; production timing, authority authentication and policy
approval remain separate work. Unconfigured ledgers preserve the previously
accepted behavior: last withdrawal becomes eligible without automatic demotion.

## Behavior

Ordinary promotion remains immediate. Ordinary demotion waits until both grace
and residence constraints have elapsed. The reducer acts only on recorded input
or clock receipts; reads do not advance time. Returning demand cancels pending
demotion, and a later withdrawal starts a new grace period. Hot is resolved before
Focus, so retained Hot membership always retains Focus too. Uni stays fixed.

A Super User restriction caps a symbol at Focus or Uni. It preserves the ordinary
requests underneath the cap, including new demand arriving while restricted.
There is one current restriction per symbol. Replacement does not create a stack:
expiry of a replacement never revives its predecessor. Clearing requires the
current restriction ID; a stale clear cannot remove a newer restriction.

A restriction defaults to the declared session end, or may end earlier. Its exact
expiry is recorded once and survives retries/restarts. A later-than-session expiry
is rejected. Clear or expiry reevaluates current valid demand; it never restores
an old membership snapshot or a withdrawn request. Actual reentry starts a fresh
residence interval. Restrictions can cap baseline Focus membership; they cannot
remove a symbol from the fixed Uni.

Authority comes from the trusted local adapter's actor context. This package
checks that identity but does not authenticate an external caller. The Super User
uses the restriction API rather than cancelling another producer's request.

## Evidence and replay

The request ledger binds its baseline and explicit policy settings into its
identity. Reopening with a different authority or timing configuration fails.
Entry and absence timers are derived from the immutable receipt history, so a
restart neither resets nor silently advances them. Exact retries keep the original
receipt; conflicting command identities fail. Rejected control actions are retained.
Hash chaining detects inconsistent stored history; it is not a cryptographic
signature or protection against an attacker rewriting the entire database.

The retained proof uses an explicitly **synthetic policy clock**. It advances
logical timestamps instantly to test exact boundaries. Its fixture begins about
ten minutes ahead of real UTC so the pinned schema-v2 store can use real publication
times without backdating. Every report and membership provenance record labels
this simulation. It establishes deterministic policy/publication behavior, not live
latency, real market acquisition or provider timing.

The trace exercises promotion, withdrawal, grace/residence boundaries, restart,
unauthorized restriction, Focus cap, Uni replacement, stale clear, expiry without
old-cap revival, clearing after both sources withdraw, fresh reentry and the Hot
retention dependency. It records 21 input receipts and 22 complete hierarchy
revisions, with zero acquisitions. Audit passes and two journal replays agree.
An injected channel insertion failure rolls back its entire hierarchy revision.

The publication bridge is an experimental adapter. A production serialized service,
clock scheduler, publication outbox/acknowledgements, authentication, recorded/live
Nasdaq ingestion and measured Hot acquisition remain to be built. No production
cadence or rate budget is selected here.

MasterBot acceptance is complete: all 43 tests and the retained proof passed on
October 16, with clean prompt return. See [VALIDATION.md](VALIDATION.md) for
local and Windows evidence and the remaining production boundaries.
