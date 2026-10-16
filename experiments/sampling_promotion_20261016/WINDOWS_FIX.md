# Windows cleanup correction

The first Windows run passed the rollback assertions but failed deleting rollback.sqlite3 during test cleanup (WinError 32). The trigger setup used sqlite3.Connection as a context manager; that commits or rolls back a transaction but does not close the connection. This package uses contextlib.closing to close that test-owned connection immediately and verifies that the handle is closed before testing rollback.

This correction changes the rollback test only. The 44 pinned reference files and the promotion/bridge implementation are unchanged. No cleanup errors are suppressed and no retries or forced deletion are introduced. The original failed run is preserved in its original folder; this new package runs independently. Actual Windows acceptance of this correction remains pending.
