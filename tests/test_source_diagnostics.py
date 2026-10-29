"""Original SQLite failure evidence survives blocking and best-effort reporting."""
from contextlib import closing
import json
import sqlite3
import unittest
from unittest.mock import patch

import test_nasdaq_recovery_supervisor as fixtures


class SourceDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.RecoverySupervisorTests('runTest')
        self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.authority=self.fixture.supervisor

    def test_real_sqlite_failure_records_code_origin_and_database_without_local_values(self):
        private_canary='SYNTHETIC-SQLITE-LOCAL-MUST-NOT-LEAK'
        self.fixture.feed.path.write_bytes(b'not a SQLite database')
        with patch.object(self.fixture.client,'attempt',wraps=self.fixture.client.attempt) as acquire:
            result=self.authority.cycle()
        self.assertEqual(result['status'],'BLOCKED',result)
        self.assertTrue(result['status_persisted'])
        failure=result['sqlite_failure']
        self.assertEqual(failure['errorcode'],sqlite3.SQLITE_NOTADB)
        self.assertEqual(failure['errorname'],'SQLITE_NOTADB')
        self.assertEqual(failure['database_path'],str(self.fixture.feed.path))
        self.assertEqual(failure['database_path_frame']['function'],'_read')
        self.assertTrue(failure['frames'])
        self.assertNotIn(private_canary,json.dumps(result))
        acquire.assert_not_called()
        self.assertIsNone(self.fixture.worker.child)
        with closing(sqlite3.connect(self.authority.path)) as c:
            saved=json.loads(c.execute('SELECT payload FROM recovery_supervisor_event ORDER BY sequence DESC LIMIT 1').fetchone()[0])
        self.assertEqual(saved['sqlite_failure'],failure)

    def test_original_details_survive_when_the_status_database_also_cannot_be_read(self):
        self.authority.path.write_bytes(b'not a SQLite database')
        result=self.authority.cycle()
        self.assertEqual(result['status'],'BLOCKED')
        self.assertFalse(result['status_persisted'])
        self.assertEqual(result['sqlite_failure']['errorname'],'SQLITE_NOTADB')
        self.assertEqual(result['sqlite_failure']['database_path'],str(self.authority.path))
        self.assertIsNone(self.fixture.worker.child)

    def test_extended_io_code_is_retained_without_retrying_the_failed_cycle(self):
        error=sqlite3.OperationalError('injected disk I/O error')
        error.sqlite_errorcode=sqlite3.SQLITE_IOERR_READ
        error.sqlite_errorname='SQLITE_IOERR_READ'
        with patch.object(self.authority,'_cycle',side_effect=error) as cycle:
            result=self.authority.run(stop_requested=lambda:False,max_seconds=1)
        self.assertEqual(result['status'],'BLOCKED')
        self.assertEqual(result['sqlite_failure']['errorcode'],sqlite3.SQLITE_IOERR_READ)
        self.assertEqual(result['sqlite_failure']['errorname'],'SQLITE_IOERR_READ')
        cycle.assert_called_once()
        self.assertIsNone(self.fixture.worker.child)

    def test_non_sqlite_integrity_failure_keeps_its_original_blocking_decision(self):
        with patch.object(self.authority,'_cycle',side_effect=ValueError('injected integrity failure')) as cycle:
            result=self.authority.cycle()
        self.assertEqual(result['status'],'BLOCKED')
        self.assertEqual(result['reasons'],['ValueError'])
        self.assertNotIn('sqlite_failure',result)
        self.assertTrue(result['failure_origin']['frames'])
        self.assertEqual(result['failure_origin']['database_path'],str(self.authority.path))
        cycle.assert_called_once()


if __name__=='__main__':unittest.main()
