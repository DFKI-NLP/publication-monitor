from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

import download_csv
import publications as pub

CSV = 'id;title;author;creationdate;year;month\n1;First paper;Example Author;19.10.2026;2026;10\n'


class PublicationTests(unittest.TestCase):
    def test_import_updates_metadata_and_keeps_invited_markers(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'papers.csv'
            path.write_text(CSV)
            initial = pub.import_csv(path, {'papers': {}, 'invited': [], 'new': []})
            self.assertEqual(initial['new'], [])
            initial['invited'] = ['1']
            path.write_text(CSV.replace('First paper', 'Updated title') + '2;New paper;Other Author;20.10.2026;;\n')
            updated = pub.import_csv(path, initial)
            self.assertEqual(updated['papers']['1']['title'], 'Updated title')
            self.assertEqual(updated['new'], ['2'])
            self.assertEqual(updated['invited'], ['1'])
            self.assertEqual(updated['papers']['2']['year'], '')

    def test_bad_csv_rejected_without_mutating_existing_data(self):
        for text in ['<html>Login</html>', 'id;title\n', 'id;title\n1;A\n1;B\n', 'id;title\n1;A;extra\n', 'id;title\n1\n']:
            with self.assertRaises(ValueError):
                pub.parse_csv(text)

    def test_invitation_wording_and_multiple_papers(self):
        papers = list(pub.parse_csv(CSV).values())
        papers.append({'id': '2', 'title': 'Second paper'})
        text = pub.invitation(papers, 'Example')
        self.assertIn('Dear Example,', text)
        self.assertIn('First paper', text)
        self.assertIn('Second paper', text)
        self.assertIn('Thursdays at 14:00', text)
        self.assertIn('Please reply to this email with your availability', text)

    def test_download_one_get_no_redirect_or_retry(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(download_csv.requests, 'get') as get:
            path = Path(directory) / 'papers.csv'
            get.return_value = Mock(status_code=200, content=CSV.encode())
            self.assertEqual(download_csv.download('test-user', 'test-password', path), 1)
            get.assert_called_once_with(download_csv.URL, auth=('test-user', 'test-password'), timeout=(15, 120), allow_redirects=False)
            self.assertEqual(path.read_text(), CSV)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_download_failure_preserves_existing_file(self):
        for status, content in [(302, b''), (500, b''), (200, b'<html>Login</html>')]:
            with tempfile.TemporaryDirectory() as directory, patch.object(download_csv.requests, 'get', return_value=Mock(status_code=status, content=content)) as get:
                path = Path(directory) / 'papers.csv'; path.write_text('existing data')
                with self.assertRaises(ValueError):
                    download_csv.download('test-user', 'test-password', path)
                get.assert_called_once()
                self.assertEqual(path.read_text(), 'existing data')

    def test_local_state_roundtrip(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'data.json'
            data = {'papers': pub.parse_csv(CSV), 'invited': ['1'], 'new': []}
            pub.save_text(path, json.dumps(data))
            self.assertEqual(pub.load(path), data)


if __name__ == '__main__':
    unittest.main()
