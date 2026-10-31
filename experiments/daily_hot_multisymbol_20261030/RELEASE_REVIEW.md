# Proposed multi-symbol operating scope — approval pending

The Windows result and actual read-only deployment review must be collected for
this exact candidate before it is presented for production activation approval.
Running the verifier or reviewing these values does not activate Hot.

| Item | Proposed bound |
|---|---|
| Hot authorization/active membership | 40 symbols |
| New symbols outside opening r1 | At most 40 per session |
| Opening capacity | Uni <=600; Focus <=40; Hot initially empty |
| Maximum resulting membership | Uni 640; Focus 80; Hot 40 |
| Quote batches | Uni <=2; Focus <=1; Hot <=1 at batch size400 |
| Hot cadence | Original24 reserved even-second slots/minute |
| Hot calls | At most9360/session; no catch-up of past slots |
| Identity calls | At most120/session, three/symbol; starts >=2s apart |
| Source | Nasdaq CURRENT/history/fresh CURRENT; original LUDP/M rules |
| Feed pacing/budget | >=60s after completion; at most390 attempts/session |
| Directory preparation | Original two-download allowance for the actual date |
| Worker starts | Original three charged starts, including replacements/resume |
| Progress / credentials | Original3s /8s |
| Replacement / cleanup / reporting | Original15s /10s /60s |
| Dispatch lateness | Original0.75s, checked again before provider dispatch |
| Membership publication | Group queued additions; ten-second minimum interval |
| Active quote-history scope | Fixed five-minute periods in one retained journal |

The identity budget includes failed/unconfirmed reservations. Same-symbol reuse,
restrictions, standard admission, nesting and durable unknown outcomes remain.
The first40 qualifying confirmations need not be the first40 feed rows when
multiple observations have equal times. Capacity overflow is retained explicitly.

New approvals can wait roughly ten seconds plus the normal pump/publication delay for effective membership. The interval is anchored in the retained publication ACK ledger across resume. Completing an interrupted native publication ACK and applying membership reductions bypass batching; immediate restrictions retain their existing priority. This replaces one new revision per identity approval during a burst. It does not alter quote polling or identity-call cadence.

## Integrity scope to review

The previous growing-prefix implementation failed full-size preparation and later
forced concurrent bursts. That evidence remains in development validation records.
This revision bounds active quote payload checks instead of relaxing the existing
deadlines. All membership history stays checked; no quote, ledger or old revision
is deleted. Closed payloads are independently compared after stop. A final native
coverage audit can pass even when a quote value has changed, so the added Hot value
integrity verdict must also pass. Two equal event-ID digests alone do not prove
payload integrity. Final reporting uses native event order without allocating full
observation projection objects; the full native replay CLI remains available.

A successful checkpoint digest is based on values verified against the native
assembled-response ledger. Final readback of an unfinished period is read-only and
cannot recover/write/dispatch. Missing original period state blocks resume; a
stored provider stop remains latched. Resume preflight performs no authentication.

## Delivery and rollback

Side-by-side extraction, no installer or main-branch change. Installed production
market-data baseline6b53ab1 and watchlist baseline e2ef6f6 remain the reviewed
requirements; dependencies remain mb-tools0.6.0, schwabdev4.0.0 and cryptography49.0.0.
A new native runtime is pinned inside this candidate; schema-v2 journal format and
existing Uni/Focus cadence remain compatible. Source/dependency/review changes
invalidate preparation and must be reviewed rather than silently adopted.

Stop/rollback requests only the reviewed owned Hot scope. Verify empty scope and
inspect final report. Continue healthy Uni/Focus/Health. Preserve membership,
journal, source evidence, period ledgers and charged budgets. There is no reset,
PID adoption, roster restoration or destructive rollback command.

## Qualification limits

Offline forced load supplies concurrency, bursts, overflow, corruption and retained
history evidence independently of natural halt frequency. It is not live-provider
capacity, an elapsed full market day or full-session operation. Accepted after-hours
and bounded real market-open proofs retain their original one-symbol scopes. A
controlled production session must supply the missing observed operating evidence.
