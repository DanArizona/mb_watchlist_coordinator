# Exact catalog and cumulative identity gate — command 42

This is the next bounded controller implementation slice after accepted Windows
command 41. It adds catalog acquisition and the identity/request boundary. It
does not expose a live controller launcher. Local qualification is 211/211 PASS
in 6.2588491409997005s, zero skips/errors/failures; Windows command 42 is pending.
Run only the offline verification:

```bat
call "FULL-EXTRACTED-FOLDER\42_verify_integrated_identity.cmd"
```

Use sea-green; nothing is installed or upgraded. No real password, vault, feed,
broker request, production journal or production process is accessed. The
source guard runs before focused tests. Complete verification requires the
final JSON report and actual CMD prompt return. Paste both.

## Implemented boundary

- Catalog acquisition requires explicit network authorization or a synthetic
  child scenario. It starts at most two owned children, one per fixed Nasdaq
  directory URL, with at most 10 seconds each and the earlier bootstrap deadline.
  Parent and child deadlines also bound hangs/orphans. No retry, redirect or
  fallback exists. Successful bytes/HTTP facts, source timestamps/footer and
  hashes are retained; failed returned bodies remain in the exception's receipts
  for the eventual controller to persist. No journal is initialized by retrieval.
- Exact plain symbols exclude test issues, ETFs and conflicting punctuation
  aliases using the reviewed shadow-catalog approach. The explicit new freshness
  guard requires a nonfuture directory footer at most seven days old, allowing
  normal prior-close/weekend evidence. Catalog membership is an instrument
  identity input, not the daily screen or a broker tradability assertion.
- Catalog artifacts are immutable and revalidated from raw bytes on every gate
  read. Normal admission uses that same catalog identity/symbol set. Changed,
  missing or corrupt inputs cannot become an empty new catalog or fresh budget.
- Identity reservation commits before the prepared client's one-symbol quote
  call. Three cumulative reservations include failed and uncertain calls, across
  reopen. The exact uncertain event is never retried automatically. A matching
  EQUITY/COE identity is required; no alias is inferred. 401/403/429 or an
  authorization callback requires a durable stop. Exception values are discarded.
- The first exact broker confirmation claims the experiment's one authorized
  symbol before normal admission. This conservative fence persists even if
  normal rules reject/cap it, cancel its demand or reopen the process. This is
  an experiment limit, not a new general production membership policy.
- Only approved events use the ordinary request store's admission, restriction,
  same-source reuse, exact retry and base outbox ACK validation. Every captured
  update and every rejected/unselected source command remains retained. A later
  halt for the selected symbol reuses verified session identity and normal active
  demand where allowed; a release update remains source evidence.

## Qualification and remaining work

Focused synthetic checks include two-source retrieval, HTML/HTTP/redirect/footer
failure, owned hard deadlines, tampering, cumulative/uncertain budgets,
cancellation and repeated halt/release facts, normal restrictions, native
publication/Hot acquisition/audit/two replays, and actual owned-process exits
after reservation, provider return and request commit. No secret canary value
from an SDK exception is retained. The initial development fixture failure is
preserved separately; it used unsupported `max_group='none'`, corrected to the
supported restriction API before packaging.

Previously accepted runtime sources are unchanged. The new gate adapts the
base outbox's pinned validators without changing that schema or bypassing
normal admission. Coupling post-credential catalog acquisition to bootstrap,
binding the prepared client into the supervisor/runtime loop, the 3s/8s worker
timing boundary and full manual controller resume remain separate work.
Directory limits are per acquisition invocation until that coupled controller
binds invocation ownership; no complete session recovery is claimed here.
Native Hot's separate cumulative 60-permit ledger remains accepted independently;
the complete 63-permit profile still needs coupled integration qualification.
Production Hot remains disabled; Overlay implementation follows the backend.
