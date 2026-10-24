# Manual-reopen test close and complete secret scan — command 47

Command 46 remains **FAILED on Windows**: 58/59 passed, one PermissionError
during the artifact secret scan after the reopen assertions; 81.00486850005109s
(runner 80.778s), actual prompt returned. The exact unreadable file is not named
in the supplied console. Its original archive, raw qualification and failure
record remain intact. The named failure sidecar was not independently uploaded.

The test's successful resumed controller still owns its controller lease when
the scan opens every file through a separate handle. Windows exclusive byte
locks can deny that second read even in the locking process; see the primary
[Microsoft file-lock documentation](https://learn.microsoft.com/en-us/windows/win32/fileio/locking-and-unlocking-byte-ranges-in-files)
and [Python msvcrt documentation](https://docs.python.org/3.12/library/msvcrt.html).
This establishes a test-lifetime defect consistent with the observed error; it
does not prove the original failed filename.

The corrected case verifies ready state, closes its owned controller, verifies
stopped state, then scans every saved file. The controller lease file must be
included. There is no lock-file exclusion, permission-error suppression or
retry that conceals an unreadable artifact. A strict test-only scanner detects
secret markers in binary files and reports an unreadable/disappearing relative
filename with safe numeric/type diagnostics. Arbitrary exception text and the
secret marker itself are not echoed.

This packet runs only affected scan/close/horizon/output-redaction checks,
including the original failing case. It complements the retained command-46
Windows result rather than repeating its unchanged functional/capacity work.
A native Windows check proves that reading a held exclusive lease through a
second handle fails, and that the same file is scanned after release. That
check is explicitly skipped on other operating systems, never called qualified
from a Linux run.

All 63 Coordinator/native/public-helper runtime source files, including the
manual-reopen implementation, must match the original command-46 archive.
Runtime code, original windows, one-symbol selection, cumulative permits,
worker generation count and 3s/8s timing gates are unchanged. No API, password,
real vault, installed SDK, public HTTP/broker request or production access is
used. There is no live controller command.

MasterBot sea-green Windows confirmation is now complete. The local,
extracted-package and Windows results remain separate records. No unchanged
command-47 or earlier accepted repeat is needed. The independent outer/profile harness, separate live profiles,
Overlay, production adoption and broader capacity remain pending.

Current-host qualification: 18 checks, **17 passed and one Windows-only check
skipped**, zero failures/errors, 14.58621698099978s (runner 9.585s).
The native Windows exclusive-read-lock check is not qualified from this host.
All 63 original command-46 runtime/reference source files match. Source-pinned
extraction also passes: 18 checks, 17 passed and the same Windows-only check
skipped, zero failures/errors, 7.720689573000072s. All 102 mapped files match
public source 178c193fdebef3abdd0ba814c4e7e08eaf51f4a7, tree
398e51dc4f4a3fef0b73d457db7a6b6df62a0de4. Altered/extra source returns 70
before tests; the complete inventory is restored. The immutable ZIP is
manual_resume_scan_20261024_005233_7b9844.zip, 310821 bytes/106 files, SHA-256
a35e11afa74c518998feb181d2da1b3a2f62c58d9ec91d42a2c6f7dcf938b5c0.
MasterBot Windows passes all 18 checks in 4.1607059999369085s (runner 3.956s),
zero skips/failures/errors, including the actual Windows lock/read check,
run 20261024T010347Z-075a6f1e and actual CMD prompt return. The raw fixed
OPERATOR_RESULT_REQUIRED label remains intact; the separate operator record
accepts this supplied console, and the saved report was not independently
uploaded. All 102 bundled files and the original ZIP are unchanged. The
original command-46 FAILED verdict and unknown original unreadable filename
remain retained. This acceptance updates documentation/records only.
