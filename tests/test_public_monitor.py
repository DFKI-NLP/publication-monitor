import copy
from datetime import date
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import public_monitor as public


class PublicMonitorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.team = self.root / 'team.csv'
        self.team.write_text('name,email,openalex_id,enabled\nExample,example@example.org,A1,true\nExcluded,excluded@example.org,A2,false\n')
        self.fixture = self.root / 'works.json'
        self.works = [{'id': 'https://openalex.org/W1', 'title': 'An example public paper', 'publication_date': date.today().isoformat(), 'doi': 'https://doi.org/10.1234/example', 'authorships': [{'author': {'id': 'https://openalex.org/A2'}}, {'author': {'id': 'https://openalex.org/A1'}}]}]
        self.fixture.write_text(json.dumps(self.works))
        self.state = self.root / 'state.json'
        self.output = self.root / 'drafts'
        self.args = ['--state', str(self.state), 'scan', '--team', str(self.team), '--fixture', str(self.fixture), '--output', str(self.output)]

    def test_end_to_end_offline_and_mark_sent(self):
        with patch('requests.sessions.Session.request', side_effect=AssertionError('No network')), patch('smtplib.SMTP', side_effect=AssertionError('No SMTP')):
            self.assertEqual(public.main(self.args), 0)
            state = public.read_state(self.state)
            self.assertEqual(len(state['records']), 1)
            key = next(iter(state['records']))
            self.assertEqual(state['records'][key]['recipient']['email'], 'example@example.org')
            draft = next(self.output.rglob('*.txt')).read_text()
            self.assertNotIn('intranet', draft.lower())
            self.assertIn('https://doi.org/10.1234/example', draft)
            self.assertEqual(public.main(['--state', str(self.state), 'mark', key, '--status', 'sent']), 0)
            self.assertEqual(public.main(self.args), 0)
            self.assertEqual(len(list(self.output.rglob('*.txt'))), 1)
            self.assertEqual(public.read_state(self.state)['records'][key]['status'], 'sent')

    def test_same_doi_deduplicates_different_work_ids(self):
        records = {}
        duplicate = copy.deepcopy(self.works[0]); duplicate['id'] = 'https://openalex.org/W2'
        public.merge_records(records, self.works + [duplicate], public.read_team(self.team), date.today())
        self.assertEqual(len(records), 1)
        self.assertIn('openalex:W2', next(iter(records.values()))['aliases'])

    def test_equal_titles_are_flagged_not_silently_merged(self):
        records = {}
        duplicate = copy.deepcopy(self.works[0]); duplicate['id'] = 'https://openalex.org/W2'; duplicate['doi'] = None
        public.merge_records(records, self.works + [duplicate], public.read_team(self.team), date.today())
        self.assertEqual(len(records), 2)
        review = public.render_review(records, self.output, 'Thursday')
        self.assertIn('Possible version duplicate', review.read_text())

    def test_old_and_unmatched_work_ignored(self):
        old = copy.deepcopy(self.works[0]); old['publication_date'] = '2000-01-01'
        unmatched = copy.deepcopy(self.works[0]); unmatched['authorships'] = [{'author': {'id': 'https://openalex.org/A2'}}]
        members = public.read_team(self.team)
        self.assertIsNone(public.normalized_work(old, members, date.today()))
        self.assertIsNone(public.normalized_work(unmatched, members, date.today()))

    def test_disabled_recipient_no_longer_gets_pending_drafts(self):
        self.assertEqual(public.main(self.args), 0)
        self.team.write_text('name,email,openalex_id,enabled\nExample,example@example.org,A1,false\nOther,other@example.org,A3,true\n')
        self.assertEqual(public.main(self.args), 0)
        self.assertEqual(len(list(self.output.rglob('*.txt'))), 1)
        self.assertFalse(next(iter(public.read_state(self.state)['records'].values()))['eligible'])

    def test_live_fetch_only_contacts_fixed_public_endpoint_and_paginates(self):
        pages = []
        for records, cursor in [(self.works, 'page2'), ([], None)]:
            response = MagicMock(status_code=200)
            response.json.return_value = {'results': records, 'meta': {'next_cursor': cursor}}
            pages.append(response)
        with patch.object(public.requests, 'Session') as session, patch.object(public.time, 'sleep'):
            client = session.return_value.__enter__.return_value
            client.get.side_effect = pages
            result = public.fetch_works({'A1': {}}, date.today(), 'synthetic-key')
            self.assertEqual(result, self.works)
            self.assertFalse(client.trust_env)
            self.assertEqual(client.get.call_count, 2)
            for call in client.get.call_args_list:
                self.assertEqual(call.args[0], 'https://api.openalex.org/works')
                self.assertFalse(call.kwargs['allow_redirects'])
                self.assertNotIn('api_key', call.kwargs['params'])
            self.assertEqual(client.get.call_args.kwargs['params']['cursor'], 'page2')

    def test_rate_limit_retries_are_bounded(self):
        with patch.object(public.requests, 'Session') as session, patch.object(public.time, 'sleep'):
            client = session.return_value.__enter__.return_value
            client.get.return_value.status_code = 429
            with self.assertRaises(ValueError):
                public.fetch_works({'A1': {}}, date.today(), 'synthetic-key')
            self.assertEqual(client.get.call_count, 3)

    def test_failed_live_fetch_does_not_change_existing_state(self):
        self.assertEqual(public.main(self.args), 0)
        before = self.state.read_bytes()
        key = self.root / 'key'; key.write_text('synthetic-key')
        with patch.object(public, 'fetch_works', side_effect=ValueError('bad response')):
            self.assertEqual(public.main(['--state', str(self.state), 'scan', '--team', str(self.team), '--live', '--key-file', str(key), '--output', str(self.output)]), 1)
        self.assertEqual(self.state.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
