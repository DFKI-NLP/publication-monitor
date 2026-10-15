import fcntl
import json
import os
from pathlib import Path
import smtplib
import tempfile
import unittest
from unittest.mock import patch

import monitor_publications as m


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name) / 'ids.json'
        self.papers = {1: {'title': 'Known'}, 2: {'title': '<New & paper>', 'author': 'Example Author', 'email': 'individual@example.org'}}

    def test_first_run_baselines_without_mail(self):
        with patch.object(m, 'fetch_publications', return_value=self.papers), patch.object(m, 'send_summary') as send:
            m.run(self.state)
            send.assert_not_called()
            self.assertEqual(m.load_state(self.state), {1, 2})

    def test_summary_and_duplicate_prevention(self):
        m.save_state(self.state, {1, 99})
        with patch.object(m, 'fetch_publications', return_value=self.papers), patch.object(m, 'send_summary') as send:
            m.run(self.state)
            m.run(self.state)
            send.assert_called_once_with({2: self.papers[2]})
            self.assertEqual(m.load_state(self.state), {1, 2, 99})

    def test_failure_keeps_pending_ids(self):
        m.save_state(self.state, {1})
        with patch.object(m, 'fetch_publications', return_value=self.papers), patch.object(m, 'send_summary', side_effect=smtplib.SMTPException('private server response')):
            with self.assertRaises(smtplib.SMTPException):
                m.run(self.state)
        self.assertEqual(m.load_state(self.state), {1})

    def test_dry_run_never_sends_or_changes_state(self):
        with patch.object(m, 'fetch_publications', return_value=self.papers), patch.object(m, 'send_summary') as send:
            m.run(self.state, True)
            self.assertFalse(self.state.exists())
            m.save_state(self.state, {1})
            m.run(self.state, True)
            self.assertEqual(m.load_state(self.state), {1})
            send.assert_not_called()

    def test_mailbox_only_envelope_and_headers(self):
        with patch.dict(os.environ, {'SMTP_USER': 'login@example.org', 'SMTP_PASS': 'test-only'}), patch.object(m.smtplib, 'SMTP') as smtp:
            m.send_summary(self.papers)
            client = smtp.return_value.__enter__.return_value
            client.starttls.assert_called_once()
            args, kwargs = client.send_message.call_args
            self.assertEqual(kwargs, {'from_addr': m.MAILBOX, 'to_addrs': [m.MAILBOX]})
            msg = args[0]
            self.assertEqual(msg['To'], m.MAILBOX)
            self.assertEqual(msg['From'], m.MAILBOX)
            self.assertIsNone(msg['Cc'])
            self.assertIsNone(msg['Bcc'])
            self.assertNotIn('individual@example.org', msg.as_string())
            self.assertNotIn('login@example.org', msg.as_string())

    def test_html_escaping(self):
        body = m.build_body(self.papers)
        self.assertIn('&lt;New &amp; paper&gt;', body)
        self.assertNotIn('<New', body)

    def test_invalid_state_is_not_overwritten(self):
        for value in ['{}', '[true]', '["1"]', 'not json']:
            self.state.write_text(value)
            with self.assertRaises((ValueError, json.JSONDecodeError)):
                m.load_state(self.state)
            self.assertEqual(self.state.read_text(), value)

    def test_concurrent_run_skips_fetch(self):
        lock_path = self.state.with_suffix('.json.lock')
        with lock_path.open('a') as lock, patch.object(m, 'fetch_publications') as fetch:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            m.run(self.state)
            fetch.assert_not_called()

    def test_fetch_validates_csv(self):
        with patch.dict(os.environ, {'DFKI_USER': 'test-user', 'DFKI_PASS': 'test-only'}), patch.object(m.requests, 'Session') as session:
            response = session.return_value.__enter__.return_value.get.return_value
            response.status_code = 200
            response.text = 'id;title\n1;Test\n'
            self.assertEqual(m.fetch_publications(), {1: {'id': '1', 'title': 'Test'}})
            for invalid in ['<html>Login</html>', 'id;title\n', 'id;title\n1;A\n1;B\n', 'id;title\n1;A;extra\n', 'id;title\nbad;A\n']:
                response.text = invalid
                with self.assertRaises(ValueError):
                    m.fetch_publications()
            response.status_code = 302
            with self.assertRaises(ValueError):
                m.fetch_publications()

    def test_secret_files(self):
        secret = Path(self.temp.name) / 'secret'
        secret.write_text('test-value\n')
        with patch.dict(os.environ, {'EXAMPLE_FILE': str(secret)}, clear=True):
            self.assertEqual(m.setting('EXAMPLE'), 'test-value')
            os.environ['EXAMPLE'] = 'conflict'
            with self.assertRaises(ValueError):
                m.setting('EXAMPLE')

    def test_errors_exit_nonzero_without_logging_secrets(self):
        with patch.object(m, 'run', side_effect=RuntimeError('private-password')), self.assertLogs(m.LOG, level='ERROR') as logs:
            self.assertEqual(m.main(['--state', str(self.state)]), 1)
        self.assertNotIn('private-password', '\n'.join(logs.output))


if __name__ == '__main__':
    unittest.main()
