import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import setup_monitor as setup


class SetupTests(unittest.TestCase):
    def test_config_roundtrip_shell_metacharacters_and_permissions(self):
        values = {'DFKI_USER': 'example', 'DFKI_PASS': "a $b `c` 'd' ; # e", 'SMTP_PASS': 'different', 'EXCLUDED_UIDS': 'head,admin'}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '.env'
            setup.write_config(path, values)
            self.assertEqual(setup.read_config(path), values)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            result = subprocess.run(['bash', '-c', 'set -a; source "$1"; printf "%s" "$DFKI_PASS"', 'test', str(path)], text=True, capture_output=True, check=True)
            self.assertEqual(result.stdout, values['DFKI_PASS'])

    def test_separate_password_prompts_and_default_mail_login(self):
        with patch('builtins.input', side_effect=['example', 'head,admin']), patch('getpass.getpass', side_effect=['intranet-secret', 'mail-secret']) as password:
            config = setup.collect_config({})
        self.assertEqual(config['SMTP_USER'], 'example@dfki.de')
        self.assertEqual(config['DFKI_PASS'], 'intranet-secret')
        self.assertEqual(config['SMTP_PASS'], 'mail-secret')
        self.assertEqual(password.call_count, 2)

    def test_existing_credentials_exclusions_and_mail_login_are_preserved(self):
        config = {'DFKI_USER': 'example', 'DFKI_PASS': 'intranet', 'SMTP_PASS': 'mail', 'SMTP_USER': 'different@example.org', 'EXCLUDED_UIDS': 'head,admin'}
        with patch('builtins.input') as prompt, patch('getpass.getpass') as password:
            saved = setup.collect_config(config)
            prompt.assert_not_called(); password.assert_not_called()
        for key, value in config.items():
            self.assertEqual(saved[key], value)

    def test_explicit_empty_exclusion_policy(self):
        with patch('builtins.input', side_effect=['example', 'NONE']), patch('getpass.getpass', return_value='test-secret'):
            self.assertEqual(setup.collect_config({})['EXCLUDED_UIDS'], '')

    def test_blank_exclusion_policy_is_rejected(self):
        with patch('builtins.input', side_effect=['example', '']), patch('getpass.getpass', return_value='test-secret'):
            with self.assertRaises(setup.SetupError):
                setup.collect_config({})

    def test_schedule_idempotent_and_preserves_unrelated_jobs(self):
        root = Path('/tmp/example installation')
        existing = 'MAILTO=""\n0 2 * * * /opt/backup\n'
        first = setup.scheduled_crontab(existing, root)
        self.assertTrue(first.startswith(existing))
        self.assertEqual(setup.scheduled_crontab(first, root), first)
        self.assertEqual(first.count('0 7 * * *'), 1)
        self.assertIn("'/tmp/example installation/monitor_publications.sh'", first)

    def test_other_monitor_schedule_is_rejected(self):
        with self.assertRaises(setup.SetupError):
            setup.scheduled_crontab('0 7 * * * /opt/old/monitor_publications.sh\n', Path('/opt/new'))

    def test_percent_is_escaped_for_cron(self):
        self.assertIn(r'\%', setup.scheduled_crontab('', Path('/tmp/test%path')))

    def test_failed_cron_read_is_not_treated_as_empty(self):
        with patch('subprocess.run', return_value=subprocess.CompletedProcess([], 1, '', 'Permission denied')):
            with self.assertRaises(setup.SetupError):
                setup.read_crontab()
        with patch('subprocess.run', return_value=subprocess.CompletedProcess([], 1, '', 'no crontab for example')):
            self.assertEqual(setup.read_crontab(), '')

    def test_validation_preserves_state_and_sends_no_mail(self):
        import monitor_publications as monitor
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / 'known.json'
            monitor.save_state(state, {1})
            with patch.dict(os.environ, {'STATE_FILE': str(state), 'SMTP_USER': 'example', 'SMTP_PASS': 'test-secret'}), patch.object(monitor, 'fetch_publications', return_value={1: {}, 2: {}}), patch.object(setup.smtplib, 'SMTP') as smtp, patch.object(monitor, 'send_email') as send:
                setup.check_access_and_baseline()
                self.assertEqual(monitor.load_state(state), {1})
                send.assert_not_called()
                smtp.return_value.__enter__.return_value.send_message.assert_not_called()
                state.unlink()
                setup.check_access_and_baseline()
                self.assertEqual(monitor.load_state(state), {1, 2})

    def test_success_installs_one_job_and_preserves_existing_cron(self):
        config = {'DFKI_USER': 'example', 'DFKI_PASS': 'test-secret', 'SMTP_USER': 'example@dfki.de', 'SMTP_PASS': 'test-secret', 'EXCLUDED_UIDS': 'head'}
        existing = '0 2 * * * /opt/backup\n'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.venv/bin').mkdir(parents=True)
            (root / '.venv/bin/python').touch()
            cwd = Path.cwd()
            try:
                with patch.object(setup, 'ROOT', root), patch.object(setup, 'read_crontab', return_value=existing), patch.object(setup, 'collect_config', return_value=config), patch.object(setup.shutil, 'which', return_value='/usr/bin/crontab'), patch.object(setup.subprocess, 'run') as run:
                    self.assertEqual(setup.main([]), 0)
                    installs = [call for call in run.call_args_list if call.args[0] == ['crontab', '-']]
                    self.assertEqual(len(installs), 1)
                    self.assertTrue(installs[0].kwargs['input'].startswith(existing))
                    self.assertEqual(installs[0].kwargs['input'].count('0 7 * * *'), 1)
            finally:
                os.chdir(cwd)

    def test_no_schedule_after_failed_access_check(self):
        config = {'DFKI_USER': 'example', 'DFKI_PASS': 'test-secret', 'SMTP_USER': 'example@dfki.de', 'SMTP_PASS': 'test-secret', 'EXCLUDED_UIDS': 'head'}
        calls = []
        def run(args, **kwargs):
            calls.append(args)
            if '--check-access' in args:
                raise subprocess.CalledProcessError(1, args)
            return subprocess.CompletedProcess(args, 0)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.venv/bin').mkdir(parents=True)
            (root / '.venv/bin/python').touch()
            cwd = Path.cwd()
            try:
                with patch.object(setup, 'ROOT', root), patch.object(setup, 'read_crontab', return_value=''), patch.object(setup, 'collect_config', return_value=config), patch.object(setup.shutil, 'which', return_value='/usr/bin/crontab'), patch.object(setup.subprocess, 'run', side_effect=run):
                    self.assertEqual(setup.main([]), 1)
                self.assertFalse(any(call == ['crontab', '-'] for call in calls))
            finally:
                os.chdir(cwd)


if __name__ == '__main__':
    unittest.main()
