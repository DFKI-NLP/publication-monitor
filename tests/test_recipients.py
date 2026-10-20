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
