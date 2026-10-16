import contextlib
from email import policy
from email.parser import BytesParser
import io
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

import draft_invitations as drafts


class DraftTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.input = self.root / 'input.json'
        self.data = {'invitations': [{'name': 'Example Researcher', 'email': 'researcher@example.org', 'publications': [{'id': 1, 'title': 'Test <paper>', 'year': '2026'}]}]}
        self.input.write_text(json.dumps(self.data))

    def test_offline_copyable_output(self):
        output = io.StringIO()
        with patch('requests.sessions.Session.request', side_effect=AssertionError('Network forbidden')), patch('smtplib.SMTP', side_effect=AssertionError('SMTP forbidden')), patch('monitor_publications.save_state', side_effect=AssertionError('State change forbidden')), contextlib.redirect_stdout(output):
            self.assertEqual(drafts.main(['--input', str(self.input), '--when', 'Friday at 10:00']), 0)
        text = output.getvalue()
        self.assertIn('To: researcher@example.org', text)
        self.assertIn('Friday at 10:00', text)
        self.assertIn('Test <paper>', text)
        self.assertEqual(list(self.root.iterdir()), [self.input])

    def test_private_text_and_eml_files(self):
        target = self.root / 'drafts'
        self.assertEqual(drafts.main(['--input', str(self.input), '--output', str(target)]), 0)
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o700)
        for path in target.iterdir():
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        msg = BytesParser(policy=policy.default).parsebytes((target / 'invitation-001.eml').read_bytes())
        self.assertEqual(msg['To'], 'researcher@example.org')
        self.assertEqual(msg['From'], 'colloquium-slt@dfki.de')
        self.assertIsNone(msg['Cc']); self.assertIsNone(msg['Bcc'])
        self.assertEqual(msg['X-Unsent'], '1')
        self.assertIn('Test &lt;paper&gt;', msg.get_body(preferencelist=('html',)).get_content())
        self.assertEqual(drafts.main(['--input', str(self.input), '--output', str(target)]), 1)

    def test_invalid_input_does_not_create_output(self):
        self.data['invitations'][0]['email'] = 'test@example.org\nBcc: other@example.org'
        self.input.write_text(json.dumps(self.data))
        target = self.root / 'drafts'
        self.assertEqual(drafts.main(['--input', str(self.input), '--output', str(target)]), 1)
        self.assertFalse(target.exists())


if __name__ == '__main__':
    unittest.main()
