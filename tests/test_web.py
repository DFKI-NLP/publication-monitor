import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest

from app import make_server

CSV = 'id;title;author;author_ou;creationdate\n1;Example paper;Example Author;Example Author (SLT);20.10.2026\n'


class WebTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.state = Path(self.folder.name) / 'publications.json'
        self.state.with_name('staff.csv').write_text('uid,name\nexau01,Example Author\n')
        self.server = make_server(self.state, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.folder.cleanup()

    def request(self, path, body=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        conn.request('GET' if body is None else 'POST', path,
                     body=None if body is None else json.dumps(body),
                     headers=headers if headers is not None else {'Content-Type': 'application/json'})
        response = conn.getresponse()
        result = response.status, response.read()
        conn.close()
        return result

    def test_upload_draft_mark_update_and_persistence(self):
        status, _ = self.request('/api/import', {'csv': CSV})
        self.assertEqual(status, 200)
        _, raw = self.request('/api/draft', {'ids': ['1']})
        self.assertEqual(json.loads(raw)['name'], 'Example Author')
        self.assertIn('Dear Example Author,', json.loads(raw)['body'])
        status, raw = self.request('/api/draft', {'ids': ['1'], 'name': 'Example'})
        draft = json.loads(raw)
        self.assertEqual(draft['recipients'], 'exau01@dfki.de')
        self.assertIn('Dear Example,', draft['body'])
        self.request('/api/mark', {'ids': ['1'], 'invited': True})
        self.request('/api/import', {'csv': CSV + '2;Another paper;Someone;Someone (SLT);20.10.2026\n'})
        saved = json.loads(self.state.read_text())
        self.assertEqual(saved['invited'], ['1'])
        self.assertEqual(saved['new'], ['2'])
        before = self.state.read_bytes()
        status, _ = self.request('/api/import', {'csv': '<html>Bad CSV</html>'})
        self.assertEqual(status, 400)
        self.assertEqual(self.state.read_bytes(), before)
        self.request('/api/mark', {'ids': ['1'], 'invited': False})
        self.assertEqual(json.loads(self.state.read_text())['invited'], [])

    def test_local_access_only_and_no_private_file_serving(self):
        self.assertEqual(self.request('/')[0], 200)
        self.assertEqual(self.request('/data/staff.csv')[0], 404)
        self.assertEqual(self.request('/api/publications', headers={'Host': 'evil.example'})[0], 403)
        self.assertEqual(self.request('/api/import', {'csv': CSV}, headers={'Content-Type': 'application/json', 'Origin': 'https://evil.example'})[0], 403)
        self.assertEqual(self.request('/api/import', {'csv': CSV}, headers={'Content-Type': 'text/plain'})[0], 403)
        self.assertFalse(self.state.exists())

    def test_separate_drafts_and_mark_only_current_recipient(self):
        self.state.with_name('staff.csv').write_text('uid,name\nexau01,Example Author\nother01,Other Author\n')
        csv = CSV + '2;Other paper;Other Author;Other Author (SLT);20.10.2026\n'
        self.request('/api/import', {'csv': csv})
        status, raw = self.request('/api/drafts', {'ids': ['1', '2']})
        self.assertEqual(status, 200)
        drafts = json.loads(raw)['drafts']
        self.assertEqual([d['recipients'] for d in drafts], ['exau01@dfki.de', 'other01@dfki.de'])
        self.assertEqual(self.request('/api/draft', {'ids': ['1', '2']})[0], 400)
        self.request('/api/mark', {'ids': drafts[0]['ids'], 'invited': True})
        self.assertEqual(json.loads(self.state.read_text())['invited'], ['1'])
