# Focused owned-exit / role-lease correction

Extract this ZIP into its own output folder. In sea-green run
`64_verify_daily_hot_exit_fix.cmd`; allow approximately 45 seconds. Supply the
final JSON and actual returned CMD prompt. No password, API, installation,
production changes or Hot activation are included.

The previous command-63 packet remains FAILED at 133/134. Its supplied Windows
capacity proof and owned Windows Job Object cleanup/reporting proof passed.
`REUSED_WINDOWS_COMPONENTS.json` is a review of that supplied output; original
Windows files were not independently read. Those unchanged components are
retained without another full-size fixture or old-packet rerun. Native source
is unchanged at 5552c5db43351d1a9ae8d376196cc99ba9c7f05d. The builder verifies
that daily_supervision.py is the only changed Coordinator runtime source from
the original frozen command-63 commit. Source inventory is checked before
imports and after qualification. This result qualifies the correction only;
it does not rewrite the original failed packet or qualify live/provider use.

The failing order is reproduced deterministically using a real OS role lease:
the worker durably saves its response, releases the lease, and waits for the
supervisor's lease probe before exiting with code 75. The corrected owner
waits at most 50 milliseconds for that exact owned process handle to confirm
exit. It sends no signal in that confirmation step. A child that stays alive
without the lease remains BLOCKED and cannot trigger a replacement.

A second regression exercises exit between the outer and inner process
polls. While a child exists at entry, the inner helper cannot start another
one. Confirmed exit must match the original reserved token/generation; the
full fifteen-second wall and elapsed hold is then charged before replacement.
The existing three-start ceiling, credential/progress deadlines, no-catch-up,
provider limits, native response/ACK recovery and cleanup bounds are unchanged.

The 15 focused checks cover both exit orderings, persistent lease loss,
ownership/freshness fences, reservation/budget gates, real full-hold recovery,
saved-response recovery without another API request, and an owned outer/native
collection/reporting smoke proof. Raw recovery audit remains FAILED for the
intentional hold/startup gaps; the proof separately requires zero unexplained
gaps and matching fresh replays. Network is denied and SDK/credentials/journals
are synthetic. New owned evidence is retained under runs; never re-extract
over an existing run or adopt synthetic roots as live state.

Windows correction acceptance and provider/deployment/rollback plus explicit
settings/activation review remain before controlled automatic Hot. Production
Hot stays disabled. Manual membership and read-only Overlay follow closely.
