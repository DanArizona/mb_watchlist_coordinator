# Isolated after-hours provider profile — October 29

User asked whether the provider-performance work can proceed with the market
closed, then explicitly said to proceed with the described bounded isolated
profile. This authorizes preparing that trial; it does not activate production
Hot or adopt daily operating settings. Public source/tests/docs/validation
publication remains authorized on experiment/checkpoint branches.

Baseline localcc8a4b3/public25feb5a2, accepted Windows72 (30/30) and Windows71
(26/26). New runtime files are after_hours_profile.py and after_hours_entry.py
only. Existing daily/production implementations and native5552c5d stay unchanged.

Fixed profile: SPY only, at most24 logical quote dispatches,120s active including
startup, accepted24 Hot seconds/one planned minute. Actual live UTC/monotonic
clocks; no shifted live session or fabricated Nasdaq event. Fresh isolated
schema-v2 journal under delivered runs/after_hours_provider_NONCE. No production
journal/process access, Nasdaq/directory queries, automatic retry, resume, or
replacement. Original3s cold/native progress,8s auth,3s request,10s cleanup and
60s final-report maxima remain. SDK token refresh may use its shared token DB.

Review binds source/dependencies/paths/limits; explicit live/closed-hours flags
precede a manual private password prompt. Both guards recheck after typing.
Every permit is durable before the provider call; errors/invalid quotes/429
latch a stop; unknown charged outcomes remain unknown. Windows Job Objects own
worker and separate reporter scopes. Parent lease/heartbeat fences the worker;
reporting follows confirmed acquisition-scope exit. Result requires24 valid
responses/acquisitions, audit PASS, two matching replays and successful
non-forced cleanup/SDK close. It qualifies only this off-hours provider/shared
native sample; the full daily controller still needs its short market-open check.

73_verify_after_hours_provider.cmd runs19 offline cases, including one actual
paced24-slot process/native proof. Its test-only constant shifted wall clock
aligns native publication/response timestamps; elapsed gates/pacing are real.
74_run_after_hours_provider.cmd uses actual installed client/clock and requires
the matching successful Windows73 record plus explicit provider-trial/closed
hours flags. It exposes no synthetic mode or user-selected journal/commands.
Windows73 and actual provider performance are pending at source freeze.

Development evidence: fourteen unit boundaries and one actual owned429/no-retry
case passed (15 tests4.620s). The initial full19 run FAILED1/19 in86.131s:23
requests completed, the final planned slot was refused because its end time was
only1microsecond after the scheduled second. Corrected the new profile's end to
last-slot+1s, preserving the existing.75s dispatch allowance without adding a
25th grid slot. Earlier initialization exposed immediate-effective publication;
roster now becomes effective at the future first slot. Original native guards
correctly refused backdating; no native guard was relaxed. Failed development
logs/metadata are retained. Corrected full proof will run once from the exact
extracted delivery, also qualifying its runner/path-with-spaces packaging.

Production context unchanged: Oct29 closed out PASS2340acquisitions/475020obs;
Friday r0 ready543Uni/0Focus/0Hot. Friday morning OV/Focusr1/polling and previous
Health Q stop remain unconfirmed. Canonical roadmap was version236 before this
work. Manual membership and read-only Overlay follow; OV shortcut stays deferred.
