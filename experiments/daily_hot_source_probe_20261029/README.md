# Focused source clock correction and SQLite evidence probe

Command 65 completed read-only on the original failed command-64 synthetic
state. All ten databases opened and returned quick_check=ok; their main-file
bytes were unchanged. This does not explain the earlier disk I/O error.
The supplied feed ledger contains a synthetic START and unknown_worker_exit,
with no saved response, before the source's separate OperationalError.

An actual-child regression reproduces that early-exit pattern with the old
fixture clock: the fixture samples its time before the parent reserves START,
then freezes the child's clock at that older time. The first progress receipt
fails the existing monotonic evidence validation and rolls back. The new
synthetic seam shares the parent's original real/logical anchors and advances
across process spawn. Existing frozen logical-clock tests remain supported;
real network attempts continue to use actual UTC. This is a demonstrated
fixture defect, not proof of the original I/O error's cause.

SQLite failures in the source authority now retain the available numeric code,
symbolic extended name, trusted module/function/line frames, and the innermost
trusted frame owner's database path when available. That path is explicitly
labeled as frame-derived context, not a guaranteed failing-file identification.
No SQL parameter, local-variable dump, credential or extra database operation
is included. The original blocking decision remains; no I/O retry or deadline
extension has been added. Evidence also survives a failed best-effort status
write. The owner smoke test reports its primary result before quote counts.
Integrity failures also retain trusted origin frames and a frame-derived path.

During local frozen-packet investigation an additional run blocked with
"Journal prefix differs from publication ledger" after a valid feed response.
Its source ledger had reported the new membership, but the saved publication
ledger subsequently had no plan/acknowledgement events. Separate traced
collection runs passed. This intermittent integrity block remains unexplained;
all failed evidence is retained. A passing run does not erase or resolve it.
This packet is a focused diagnostic candidate, not an operating release.

Run 66_verify_daily_hot_source.cmd in sea-green. It runs 18 offline checks:
13 feed checks, four SQLite diagnostic checks and one actual owned collection
proof, including two native Hot acquisitions, a valid synthetic feed response,
native audit and two fresh equal replays. It saves verification.json and the
source/feed evidence beneath its own runs folder. Allow about 15 seconds.
No password, broker SDK, provider request, installation or production change.

The source-native candidate remains 5552c5d; installed production remains
6b53ab1. Native source, acquisition gates, ownership/replacement behavior and
the 3-second progress, 8-second authentication, 15-second replacement hold
and 10-second cleanup limits are unchanged. Prior Windows capacity and
lease/exit recovery component passes remain recorded; those drills are not
repeated. Commands 63 and 64 retain their original FAILED verdicts. This
packet does not qualify provider/full-day capacity or enable live Hot.
A passing Windows probe still does not identify the earlier transient I/O
cause. A recurring failure should now carry substantially better evidence.
