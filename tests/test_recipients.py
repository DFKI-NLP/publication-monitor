import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
import publications as pub


class RecipientTests(unittest.TestCase):
    def test_exclusions_and_deduplication(self):
        with TemporaryDirectory() as folder:
            folder = Path(folder)
            (folder / 'staff.csv').write_text('uid,name\nhead01,Example Head\nperson01,Example Researcher\n')
            (folder / 'excluded_uids.txt').write_text('head01\n')
            staff = pub.load_staff(folder)
            paper = {'author_ou': 'Example Head (FB/FG SLT), Example Researcher (FB/FG SLT)'}
            self.assertEqual(pub.recipients([paper, paper], staff), ['person01@dfki.de'])

    def test_ambiguous_unknown_and_non_slt_not_suggested(self):
        staff = [{'uid': 'one01', 'name': 'Example Person'}, {'uid': 'two01', 'name': 'Example Person'}]
        for authors in ('Example Person (SLT)', 'Unknown Person (SLT)', 'Example Person (MLT)'):
            self.assertEqual(pub.recipients([{'author_ou': authors}], staff), [])

    def test_name_normalization(self):
        self.assertEqual(pub.name_key('Müller, Anna'), pub.name_key('Anna Muller'))

    def test_names_match_recipient_ids_and_deduplicate(self):
        staff = [{'uid': 'exau01', 'name': 'Example Author'}]
        paper = {'author_ou': 'Example Author (SLT)'}
        self.assertEqual(pub.matched_contacts([paper, paper], staff), staff)

    def test_individual_drafts_group_only_same_colleague(self):
        staff = [{'uid': 'al01', 'name': 'Alice Example'}, {'uid': 'bo01', 'name': 'Bob Example'}]
        papers = [
            {'id': '1', 'title': 'Alice first', 'author_ou': 'Alice Example (SLT)'},
            {'id': '2', 'title': 'Bob paper', 'author_ou': 'Bob Example (SLT)'},
            {'id': '3', 'title': 'Alice second', 'author_ou': 'Alice Example (SLT)'},
            {'id': '4', 'title': 'Unknown first'},
            {'id': '5', 'title': 'Unknown second'},
        ]
        groups = pub.invitation_groups(papers, staff)
        self.assertEqual(len(groups), 4)
        self.assertEqual(groups[0]['ids'], ['1', '3'])
        self.assertEqual(groups[0]['recipients'], 'al01@dfki.de')
        self.assertIn('Dear Alice Example,', groups[0]['body'])
        self.assertNotIn('Bob paper', groups[0]['body'])
        self.assertEqual(groups[1]['ids'], ['2'])
        self.assertEqual(groups[1]['recipients'], 'bo01@dfki.de')
        self.assertEqual(groups[2]['ids'], ['4'])
        self.assertEqual(groups[3]['ids'], ['5'])
