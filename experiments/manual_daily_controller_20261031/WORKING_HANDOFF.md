# Combined daily controller checkpoint — October 31

User authorized agenda step 1: enable Nasdaq and manual requests together in a
separate controller candidate, with shared capacity and durable feedback. Manual
outside-Uni identity integration remains step 2. Approved p85 is untouched.

Implemented a sealed manual-40-v1 profile and shared admission policy checked in
the ordinary request SQLite write transaction and replay. Both sources share 40
distinct Hot slots and 40 additions beyond opening Focus; withdrawals/restrictions
do not reset charges. Existing outside-Uni and provider budgets remain. Manual
outside-Uni is rejected at the backend as requiring identity confirmation.

Daily attachment, worker reader, operating review, controller, native period
collector/reporting and owned roles recognize the explicit profile. The normal
manual GUI attaches to an existing controller configuration/invocation and checks
the active ownership fence before writes. Missing/stopped/stale/replaced owners
are rejected. No GUI can initialize/reset a controller or rebind p85.

Local results before final packet extraction:

- 23 new combined checks passed in 15.940s (19 ledger/session cases and 4 owned
  cases). The actual controller collected a manual IBM + Nasdaq MSFT roster with
  one identity call and one Hot worker. Manual resume retained the original
  starts/receipts and original 15-second hold boundary, and fenced the old window;
  the unchanged elapsed full-hold drill was not repeated. Final native audit,
  Hot stored-content validation and ordered-event digest equality then passed in
  a separate affected owned-report check (8.510s including process run).
- 176 existing manual/request/policy/admission regressions passed in 2.144s.
- 83 prior daily session/review/public-launch/multi-identity cases passed in
  29.215s, including unchanged original policy hashes. Long full-history, paced
  source/recovery and provider drills were not repeated.
- The first development owned check failed only because it inspected a child
  handle after close had deliberately cleared that field. The corrected check
  retains the original actual handle and observes exit. No runtime gate changed.
- A later development proof-summary query used a nonexistent observation-level
  channel column. It now joins the acquisition table for channel selection;
  collection, audit/content checks and ownership were already passing. This
  changes proof reporting, not the native schema or runtime.
- After that query correction, the affected combined collection/final-report
  check passed in 8.481s. Python parsing and whitespace checks also passed.

The final exact ZIP, source commit 509ffa1, was independently extracted and all
272 inventoried files verified. Its 45-check suite passed in 17.127s (17.358s
including proof reporting), with native audit/content checks and matching replay
digests. The packet is 801,641 bytes; DELIVERY.json records its SHA-256 and
LOCAL_QUALIFICATION.json retains the exact Linux report. No desktop was available
locally, so the actual Tk preview is pending on Windows.

Windows qualification remains pending
until the operator runs command92 and supplies the report and returned prompt.
No new production approval, live provider evidence or full-day qualification is
claimed. Later public publication uses the existing explicitly approved
experiment/manual-membership-20261031 destination and standing ordinary source/
test/documentation authorization; honor any automatic-review rejection.
