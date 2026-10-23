from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from mb_watchlist_coordinator.authenticated_startup import StartupError
from mb_watchlist_coordinator.supervised_hot_worker import CONTRACT, RuntimeQuoteClient, progress_path, progress_receipt
from mb_watchlist_coordinator.sampling_requests import utc_text


class ProgressReceiptTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.at = datetime.now(timezone.utc)
        self.job = {'job_path': str(Path(tmp.name)/('a'*32+'.job.json')), 'token': 'a'*32,
            'generation': 1, 'started_at_utc': utc_text(self.at),
            'identity': {'startup_context': {'configuration_sha256': 'b'*64}}}
        self.value = {'contract': CONTRACT, 'token': self.job['token'], 'generation': 1,
            'configuration_sha256': 'b'*64, 'status': 'first_completed_work_observed',
            'observed_at_utc': utc_text(self.at+timedelta(seconds=2)), 'pid': 12345}

    def read(self, **updates):
        progress_path(self.job).write_text(json.dumps(dict(self.value, **updates)))
        return progress_receipt(self.job)

    def test_exact_completed_work_before_three_seconds_is_accepted(self):
        self.assertEqual(self.read(), self.value)

    def test_a_credential_receipt_is_not_a_native_progress_receipt(self):
        with self.assertRaises(ValueError): self.read(status='credentials_accepted')

    def test_equal_or_later_three_second_completion_is_rejected(self):
        for seconds in (3, 4):
            with self.assertRaises(ValueError): self.read(observed_at_utc=utc_text(self.at+timedelta(seconds=seconds)))

    def test_wrong_generation_token_configuration_extra_and_boolean_are_rejected(self):
        for value in ({'generation': 2}, {'token': 'c'*32}, {'configuration_sha256': 'c'*64},
                {'extra': 'unexpected'}, {'generation': True}, {'pid': True}):
            with self.assertRaises(ValueError): self.read(**value)

    def test_a_late_deadline_receipt_is_diagnostic_not_a_successful_start(self):
        value = self.read(status='worker_startup_deadline_ended', observed_at_utc=utc_text(self.at+timedelta(seconds=3.2)))
        self.assertEqual(value['status'], 'worker_startup_deadline_ended')


class RuntimeClientTests(unittest.TestCase):
    def test_rate_limit_is_returned_once_then_blocks_further_dispatch(self):
        calls = []
        class Client:
            halt_reason = None
            def quotes(self, symbols, *, fields):
                calls.append(symbols)
                return type('Response', (), {'status_code': 429})()
            def close(self): calls.append('closed')
        client = RuntimeQuoteClient(Client())
        self.assertEqual(client.quotes(['NVDA'], fields='all').status_code, 429)
        with self.assertRaises(StartupError): client.quotes(['NVDA'], fields='all')
        client.close(); self.assertEqual(calls, [['NVDA'], 'closed'])
