# Validation - Windows connection-closure correction, October 16, 2026

The first Windows run executed 18 tests: 17 passed, including the real-store/audit/two-replay integration test. The rollback test reached temporary-directory cleanup and failed with WinError 32 because its trigger-setup connection remained open. The runner correctly stopped before the separately retained proof.

The correction explicitly closes that one test-owned SQLite connection with contextlib.closing. The same rollback test now requires a closed-handle ProgrammingError before continuing. A local regression check using the original connection pattern fails this new assertion, demonstrating that the guard detects the defect even on Linux.

Correction validation on local Python 3.12.14:

- All 18 focused tests pass.
- The self-contained launcher executes with Python -I -B and finishes successfully.
- Separate retained proof: atomic r0/r1 publication, journal audit, idempotent retry and two identical replays PASS.
- Two global revisions, six channel revisions, ten historical member rows, zero acquisitions/observations/skips.
- The 44 pinned original reference files, promotion projection, bridge and launcher match the earlier bundle byte for byte.
- Standing baseline validation: all 138 original Coordinator tests passed before this test-only correction.

Local proof sequence SHA-256: `5dd92c147fa60c6cefc8aa5a669c61b2169f6972cd7483196b20ba107b4768b9`.
See `validation/proof_report.json`, `test_results.txt`, and `run_receipt.json`. Paths in these examples identify the local validation host. A new run creates its own journal and reports with actual current timestamps.

The Windows CMD file retains CRLF line endings and quoted paths. Actual Windows acceptance of the correction is pending a rerun. No cleanup errors are suppressed, and no forced deletion or cleanup retry masks an open handle. Production polling remains independent.
