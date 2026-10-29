# Windows process-record read correction

Run 71_verify_windows_evidence_read.cmd once in a separate sea-green CMD.
This is a self-contained offline candidate; keep earlier packets and run
records. No password, actual broker SDK/vault/provider, production journal,
source installation or activation is involved. Allow about 2.5 minutes.

Windows command 70 captured the initiating runtime operation: recovery_workers
_heartbeat read_text raised PermissionError, errno 13, with no winerror, on
the owned worker's heartbeat JSON. Its previous bound heartbeat was valid,
age .120609 seconds versus the original 3-second stale limit. The monitor
raised before its generic stop handler; the outer stale label followed.
This is a real runtime resilience gap, rather than a failure in the test's
stop callback. The precise competing handle/actor is not established.

Windows read/rename sharing windows are a documented plausible mechanism:
https://bugs.python.org/issue46003
https://devblogs.microsoft.com/oldnewthing/20211022-00/?p=105822
https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew
These sources do not prove the original actor, Defender involvement, or that
earlier SQLite/ledger/native-crash incidents share this cause.

The candidate retries only a Windows process-record PermissionError with
winerror 5/32/33 or bare EACCES, for at most .25 seconds and 26 attempts.
It reopens and reads a complete value each time; it never reuses an old
heartbeat or resets a timestamp. Persistent denial, missing files and unrelated
errors still propagate. JSON parsing, checksum/identity, ownership, three-second
freshness, startup/credential, replacement-hold and cleanup checks remain.
The existing writer remains unchanged. Shared daily process reads and dynamic
publication-status reads use the same helper so those readers do not retain
the demonstrated gap. No provider/API operation or state mutation is retried.

Windows qualification selects 26 checks: nine read/freshness cases, thirteen
existing ownership/fence cases, three native Windows file-sharing cases and
the original actual CURRENT/history/fresh-CURRENT proof. Native sharing checks
hold a known DELETE-access handle to reproduce the old CRT read failure,
release it and verify recovery; persistent conflicts must still fail. Four
concurrent readers also check 64 actual atomic publications for complete data.
The injected handle proves this mechanism in a controlled fixture, not the
identity of the actor in the original operator run.

The original paced test's source/assertions and actual 60-second feed pacing
are unchanged; exactly its two test-only periodic stack flags are off in memory.
Original outer/monitor exception observers remain to expose any new failure
directly in final JSON. Full-size capacity and the accepted recovery hold
proofs are reused without unchanged repeats. Original Windows commands
67/68/69/70 remain FAILED; a new PASS does not rewrite those verdicts.

Local qualification: 22 component checks PASS in 1.208 seconds and the one
original paced proof PASS in 126.572 seconds, in separate invocations. Three
valid attempts retain 60.702353/60.803616-second intervals, READY_WITH_GAPS,
26 native Hot acquisitions/two after reconciliation, one identity permit and
one worker start. Native audit and equal 29-event replays PASS; owned cleanup
completed in .061 seconds. This Linux regression does not exercise native
Windows sharing; injected read/freshness cases cover the new branch locally.
Windows native sharing qualification and full packet result remain pending.

Provide final JSON and actual returned CMD prompt. A PASS qualifies this
focused offline candidate, not provider capacity, a full live day or production
Hot activation. Earlier I/O/ledger-change/native-crash causes remain unassigned.
