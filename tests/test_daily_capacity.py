"""Representative synthetic storage size, actual elapsed native tail/startup."""
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from capacity_probe import run
from daily_capacity_fixture import owned_cold_startup


class DailyCapacityTests(unittest.TestCase):
    def test_full_history_owned_startup_and_elapsed_tail_audit_and_two_fresh_replays(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'capacity_qualification'
            try:
                result=run(root,background=True,full_quote=True,elapsed_ticks=True,
                    verify_journal=True,after_seed=owned_cold_startup)
                self.assertTrue(result['raw_processing_fits_current_gates'],result['tail'])
                self.assertEqual(result['owned_cold_startup']['result'],'PASS',result['owned_cold_startup'])
                self.assertLess(result['owned_cold_startup']['job_to_first_native_work_seconds'],3)
                self.assertTrue(result['native_audit_passed'],result['audit']['findings'])
                self.assertTrue(result['two_fresh_replays_equal'])
                self.assertEqual(result['first_replay']['events'],11703)
                self.assertEqual(result['audit']['table_counts']['quote_acquisition'],11700)
                self.assertEqual(result['audit']['table_counts']['quote_observation'],542099)
                self.assertEqual({r['channel']:r['acquisition_count'] for r in result['audit']['channels']},
                    {'uni':780,'focus':1560,'hot':9360})
                self.assertTrue(all(r['status_counts']=={'quote':r['observation_count']}
                    for r in result['audit']['channels']))
                self.assertFalse(result['provider_capacity_qualified'])
                self.assertFalse(result['full_session_executed'])
                result['qualification_result']='PASS'
                (root/'capacity-qualification.json').write_text(json.dumps(result,indent=2)+'\n')
            finally:
                output=os.environ.get('MB_DAILY_OPERATING_CAPACITY_DIR')
                if output and root.exists():shutil.copytree(root,output)


if __name__=='__main__':unittest.main()
