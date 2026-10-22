import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import contacts
import monitor_publications as monitor
import publication_export as export


class ApprovedUpdateTests(unittest.TestCase):
    def test_uid_addresses_no_profile_requests_for_local_staff(self):
        roster = [{'uid': 'al01', 'name': 'Alice Example'}, {'uid': 'bo01', 'name': 'Bob Example'}]
        with patch.object(contacts, 'staff_roster', return_value=roster), patch.object(contacts, 'verwalter_uids', return_value=[('head01', 'Head'), ('bo01', 'Bob Example')]), patch.object(contacts, 'fetch_staff_profile') as profile, patch.object(contacts, 'staff_uid_by_name') as search:
            result = contacts.resolve_contacts(Mock(), '2', 'Alice Example (SLT)', {'head01'})
            self.assertEqual([row[1] for row in result], ['bo01@dfki.de', 'al01@dfki.de'])
            profile.assert_not_called()
            search.assert_not_called()

    def test_unknown_manager_only_checks_membership_not_email(self):
        with patch.object(contacts, 'staff_roster', return_value=[]), patch.object(contacts, 'verwalter_uids', return_value=[('bo01', 'Bob Example')]), patch.object(contacts, 'fetch_staff_profile', return_value='Speech and Language Technology') as profile, patch.object(contacts, 'staff_uid_by_name', return_value='bo01'):
            result = contacts.resolve_contacts(Mock(), '2', 'Bob Example (SLT)', set())
            self.assertEqual([row[1] for row in result], ['bo01@dfki.de'])
            profile.assert_called_once()

    def test_one_export_get_and_saved_csv(self):
        text = 'id;title\n1;Example\n'
        with tempfile.TemporaryDirectory() as folder, patch.object(export.requests, 'Session') as session:
            response = Mock(status_code=200, text=text)
            session.return_value.__enter__.return_value.get.return_value = response
            output = Path(folder) / 'publications.csv'
            with patch.dict(os.environ, {'CSV_OUTPUT': str(output)}):
                result = export.fetch_publications('dummy', 'dummy')
            self.assertEqual(set(result), {1})
            session.return_value.__enter__.return_value.get.assert_called_once_with(export.CSV_URL, timeout=(15, 120), allow_redirects=False)
            self.assertEqual(output.read_text(), text)

    def test_known_history_not_reinvited_and_digest_only_shared_mailbox(self):
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder) / 'known.json';state.write_text('[1]')
            papers = {1: {'title': 'Old'}, 2: {'title': 'New'}}
            invitations = [{'name': 'Alice', 'email': 'al01@dfki.de', 'papers': {2: papers[2]}}, {'name': 'Bob', 'email': 'bo01@dfki.de', 'papers': {2: papers[2]}}]
            with patch.object(monitor, 'fetch_publications', return_value=papers), patch.object(monitor, 'plan_invitations', return_value=(invitations, [])) as plan, patch.object(monitor, 'send_email') as mail:
                monitor.run(state)
                plan.assert_called_once_with({2: papers[2]})
                self.assertEqual([call.args[2] for call in mail.call_args_list], [['al01@dfki.de'], ['bo01@dfki.de'], ['colloquium-slt@dfki.de']])
                self.assertEqual(json.loads(state.read_text()), [1, 2])
                mail.reset_mock();monitor.run(state);mail.assert_not_called()


if __name__ == '__main__':
    unittest.main()
