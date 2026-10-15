import fcntl
import json
import os
from pathlib import Path
import smtplib
import tempfile
import unittest
from unittest.mock import patch

import monitor_publications as m
import contacts as c
from datetime import date


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name) / 'ids.json'
        self.rec = {'name': 'Example Author', 'email': 'author@dfki.de', 'papers': {2: {'title': 'New'}}}
        plan = patch.object(m, 'plan_invitations', return_value=([self.rec], []))
        self.plan = plan.start()
        self.addCleanup(plan.stop)
        self.papers = {1: {'title': 'Known'}, 2: {'title': '<New & paper>', 'author': 'Example Author', 'email': 'individual@example.org'}}

    def test_first_run_baselines_without_mail(self):
        with patch.object(m, 'fetch_publications', return_value=self.papers), patch.object(m, 'send_email') as send:
            m.run(self.state)
            send.assert_not_called()
            self.assertEqual(m.load_state(self.state), {1, 2})

    def test_summary_and_duplicate_prevention(self):
        m.save_state(self.state, {1, 99})
        with patch.object(m, 'fetch_publications', return_value=self.papers), patch.object(m, 'send_email') as send:
            m.run(self.state)
            m.run(self.state)
            self.assertEqual(send.call_count, 2)
            self.assertEqual(send.call_args_list[0].args[2], ['author@dfki.de'])
            self.assertEqual(send.call_args_list[1].args[2], [m.MAILBOX])
            self.assertEqual(m.load_state(self.state), {1, 2, 99})

    def test_delivery_failure_records_batch_to_avoid_reinviting(self):
        m.save_state(self.state, {1})
        with patch.object(m, 'fetch_publications', return_value=self.papers), patch.object(m, 'send_email', side_effect=smtplib.SMTPException('private server response')):
            with self.assertRaises(smtplib.SMTPException):
                m.run(self.state)
        self.assertEqual(m.load_state(self.state), {1, 2})

    def test_dry_run_never_sends_or_changes_state(self):
        with patch.object(m, 'fetch_publications', return_value=self.papers), patch.object(m, 'send_email') as send:
            m.run(self.state, True)
            self.assertFalse(self.state.exists())
            m.save_state(self.state, {1})
            m.run(self.state, True)
            self.assertEqual(m.load_state(self.state), {1})
            send.assert_not_called()

    def test_digest_only_envelope_and_headers(self):
        with patch.dict(os.environ, {'SMTP_USER': 'login@example.org', 'SMTP_PASS': 'test-only'}), patch.object(m.smtplib, 'SMTP') as smtp:
            m.send_digest([self.rec], [], set())
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

    def test_invitation_direct_envelope(self):
        with patch.dict(os.environ, {'SMTP_USER': 'login@example.org', 'SMTP_PASS': 'test-only'}), patch.object(m.smtplib, 'SMTP') as smtp:
            m.send_email('Invitation', m.invitation_body(self.rec), [self.rec['email']])
            args, kwargs = smtp.return_value.__enter__.return_value.send_message.call_args
            self.assertEqual(kwargs['to_addrs'], ['author@dfki.de'])
            self.assertEqual(args[0]['To'], 'author@dfki.de')
            self.assertEqual(args[0]['Reply-To'], m.MAILBOX)
            self.assertNotIn('No individual invitations', args[0].as_string())

    def test_failed_invitation_reported_only_in_shared_digest(self):
        m.save_state(self.state, {1})
        def delivery(subject, body, recipients):
            if recipients != [m.MAILBOX]:
                raise smtplib.SMTPRecipientsRefused('synthetic failure')
        with patch.object(m, 'fetch_publications', return_value=self.papers), patch.object(m, 'send_email', side_effect=delivery) as send:
            with self.assertRaises(RuntimeError):
                m.run(self.state)
            self.assertEqual(send.call_args.args[2], [m.MAILBOX])
            self.assertIn('FAILED to send', send.call_args.args[1])
        self.assertEqual(m.load_state(self.state), {1, 2})

    def test_fetch_failure_keeps_state(self):
        m.save_state(self.state, {1})
        with patch.object(m, 'fetch_publications', side_effect=ValueError('invalid data')):
            with self.assertRaises(ValueError):
                m.run(self.state)
        self.assertEqual(m.load_state(self.state), {1})


class ContactTests(unittest.TestCase):
    def test_manager_and_author_when_distinct(self):
        profile = c.SLT_PROFILE_MARKER + ' <a href="mailto:manager@dfki.de">Mail</a>'
        with patch.object(c, 'verwalter_uids', return_value=[('manager-id', 'Manager')]), patch.object(c, 'fetch_staff_profile', return_value=profile), patch.object(c, 'staff_uid_by_name', return_value='author-id'), patch.object(c, 'email_for_uid', return_value='author@dfki.de'):
            contacts = c.resolve_contacts(None, '1', 'Example Author (FB/FG SLT)', set())
            self.assertEqual([x[1] for x in contacts], ['manager@dfki.de', 'author@dfki.de'])

    def test_excluded_manager_and_author_are_skipped(self):
        with patch.object(c, 'verwalter_uids', return_value=[('excluded-id', 'Excluded')]), patch.object(c, 'fetch_staff_profile') as profile, patch.object(c, 'staff_uid_by_name', side_effect=['excluded-id', 'eligible-id']), patch.object(c, 'email_for_uid', return_value='eligible@dfki.de') as email:
            contacts = c.resolve_contacts(None, '1', 'Excluded Author (FB/FG SLT), Eligible Author (FB/FG SLT)', {'excluded-id'})
            profile.assert_not_called()
            email.assert_called_once_with(None, 'eligible-id')
            self.assertEqual([x[1] for x in contacts], ['eligible@dfki.de'])

    def test_duplicate_address_invited_once(self):
        profile = c.SLT_PROFILE_MARKER + ' mailto:Same@dfki.de'
        with patch.object(c, 'verwalter_uids', return_value=[('manager-id', 'Manager')]), patch.object(c, 'fetch_staff_profile', return_value=profile), patch.object(c, 'staff_uid_by_name', return_value='author-id'), patch.object(c, 'email_for_uid', return_value='same@dfki.de'):
            contacts = c.resolve_contacts(None, '1', 'Example Author (FB/FG SLT)', set())
            self.assertEqual(len(contacts), 1)

    def test_non_slt_manager_is_skipped(self):
        with patch.object(c, 'verwalter_uids', return_value=[('manager-id', 'Manager')]), patch.object(c, 'fetch_staff_profile', return_value='Other department mailto:manager@dfki.de'):
            self.assertEqual(c.resolve_contacts(None, '1', 'External Author (FB/FG MLT)', set()), [])

    def test_planning_groups_papers_and_filters_old_work(self):
        papers = {1: {'year': str(date.today().year), 'month': str(date.today().month), 'author_ou': 'Example Author (FB/FG SLT)'}, 2: {'year': '2000', 'month': '1'}, 3: {'year': str(date.today().year), 'month': str(date.today().month)}}
        with patch.dict(os.environ, {'EXCLUDED_UIDS': 'head-id,admin-id', 'DFKI_USER': 'test', 'DFKI_PASS': 'test'}), patch.object(m, 'resolve_contacts', return_value=[('Author', 'author@dfki.de', 'SLT author')]) as resolve:
            invited, skipped = m.plan_invitations(papers)
            self.assertEqual(len(invited), 1)
            self.assertEqual(set(invited[0]['papers']), {1, 3})
            self.assertEqual([x[0] for x in skipped], [2])
            self.assertEqual(resolve.call_args.args[3], {'head-id', 'admin-id'})

    def test_only_first_eligible_slt_author(self):
        with patch.object(c, 'verwalter_uids', return_value=[]), patch.object(c, 'staff_uid_by_name', return_value='author-id') as lookup, patch.object(c, 'email_for_uid', return_value='author@dfki.de'):
            contacts = c.resolve_contacts(None, '1', 'First Author (FB/FG SLT), Second Author (FB/FG SLT)', set())
            self.assertEqual(len(contacts), 1)
            lookup.assert_called_once_with(None, 'First Author')


if __name__ == '__main__':
    unittest.main()
