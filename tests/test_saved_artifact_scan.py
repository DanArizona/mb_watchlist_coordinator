import os
from pathlib import Path
import tempfile
import unittest

from saved_artifact_scan import scan_saved_artifacts
from mb_watchlist_coordinator.sampling_service import owner_lock

MARKER=b'SYNTHETIC-SCAN-SECRET-47'


class SavedArtifactScanTests(unittest.TestCase):
    def test_every_saved_file_including_lock_and_binary_artifacts_is_scanned(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'state').mkdir()
            for name,data in (('controller.owner.lock',b'0'),('state/evidence.sqlite3',b'\0binary\xff'),('receipt.json',b'{}')):
                (root/name).write_bytes(data)
            scanned=scan_saved_artifacts(root,(MARKER,))
            self.assertEqual(set(scanned),{'controller.owner.lock','state/evidence.sqlite3','receipt.json'})

    def test_secret_in_binary_artifact_fails_without_echoing_the_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'evidence.sqlite3').write_bytes(b'\0prefix'+MARKER+b'\0')
            with self.assertRaises(AssertionError) as caught:scan_saved_artifacts(root,(MARKER,))
            self.assertIn('evidence.sqlite3',str(caught.exception));self.assertNotIn(MARKER.decode(),str(caught.exception))

    def test_permission_failure_is_not_skipped_and_reports_the_exact_relative_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'controller.owner.lock').write_bytes(b'0')
            def denied(path):raise PermissionError(13,'UNTRUSTED-EXCEPTION-MESSAGE')
            with self.assertRaises(AssertionError) as caught:
                scan_saved_artifacts(root,(MARKER,),read_bytes=denied)
            text=str(caught.exception)
            self.assertIn('controller.owner.lock',text);self.assertIn('PermissionError',text)
            self.assertIn('errno=13',text);self.assertNotIn('UNTRUSTED-EXCEPTION-MESSAGE',text)

    def test_disappearing_artifact_is_a_failure_instead_of_a_clean_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'saved.json').write_bytes(b'{}')
            def gone(path):path.unlink();raise FileNotFoundError(2,'UNTRUSTED-EXCEPTION-MESSAGE')
            with self.assertRaises(AssertionError) as caught:scan_saved_artifacts(root,(MARKER,),read_bytes=gone)
            self.assertIn('saved.json',str(caught.exception));self.assertIn('FileNotFoundError',str(caught.exception))

    @unittest.skipUnless(os.name=='nt','Actual Windows byte-range read locks require Windows')
    def test_native_windows_held_lease_blocks_second_handle_and_released_lease_is_scanned(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'controller.owner.lock'
            with owner_lock(path):
                with self.assertRaises(PermissionError):path.read_bytes()
            self.assertIn('controller.owner.lock',scan_saved_artifacts(root,(MARKER,)))
