import json
from pathlib import Path
import tempfile
import unittest

from mb_watchlist_coordinator.controller_resume import ResumeError,CONTRACT
from mb_watchlist_coordinator.resume_entry import parse_receipt


class ResumeReceiptTests(unittest.TestCase):
    def receipt(self):
        return {'contract':CONTRACT,'configuration_sha256':'a'*64,'result':'PASS','reason':'resume_ready',
            'reopened':True,'client_close_invoked':True,'native_poll_run_registered_by_reopen':False,
            'directory_attempts_started':0,'feed_attempts_started_by_reopen':0,
            'quote_dispatches_started_by_reopen':0,'outer_profile_harness_qualified':False,'production_access':False}

    def test_exact_redacted_reopen_receipt_is_accepted(self):
        value=self.receipt();self.assertEqual(parse_receipt(json.dumps(value),'a'*64),value)

    def test_wrong_binding_and_unknown_output_are_not_echoed(self):
        for raw,sha in ((json.dumps(self.receipt()),'b'*64),('SYNTHETIC-RESUME-SECRET','a'*64)):
            with self.subTest(sha=sha),self.assertRaises(ResumeError) as caught:parse_receipt(raw,sha)
            self.assertNotIn('SYNTHETIC-RESUME-SECRET',str(caught.exception))

    def test_duplicate_keys_and_arbitrary_sdk_fields_are_refused(self):
        value=self.receipt();value['sdk_exception']='SYNTHETIC-RESUME-SECRET'
        for raw in (json.dumps(value),json.dumps(self.receipt())[:-1]+',"result":"PASS"}'):
            with self.subTest(raw=raw),self.assertRaises(ResumeError):parse_receipt(raw,'a'*64)

    def test_reopen_cannot_claim_live_profile_or_production_or_new_dispatch(self):
        for key in ('outer_profile_harness_qualified','production_access','native_poll_run_registered_by_reopen',
                'directory_attempts_started','feed_attempts_started_by_reopen','quote_dispatches_started_by_reopen'):
            value=self.receipt();value[key]=True if type(value[key]) is bool else 1
            with self.subTest(key=key),self.assertRaises(ResumeError):parse_receipt(json.dumps(value),'a'*64)

    def test_boolean_counter_and_false_success_close_are_refused(self):
        for key,replacement in (('directory_attempts_started',False),('reopened',False),('client_close_invoked',False)):
            value=self.receipt();value[key]=replacement
            with self.subTest(key=key),self.assertRaises(ResumeError):parse_receipt(json.dumps(value),'a'*64)

    def test_deadline_failure_is_an_explicit_failure(self):
        value=self.receipt();value.update(result='FAILED',reason='credential_deadline_ended',reopened=False,client_close_invoked=False)
        self.assertEqual(parse_receipt(json.dumps(value),'a'*64)['result'],'FAILED')

    def test_diagnostic_trace_ignores_arbitrary_exception_values(self):
        from resume_failure_evidence import safe_trace
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'synthetic-controller-log.jsonl'
            path.write_text(json.dumps({'event':'fixed_exception','function':'resume_manual','line':10,
                'exception_type':'ValueError','exception_message':'SYNTHETIC-RESUME-SECRET'})+'\n')
            value=safe_trace(path)
            self.assertEqual(value[0]['exception_type'],'ValueError')
            self.assertNotIn('SYNTHETIC-RESUME-SECRET',json.dumps(value))
