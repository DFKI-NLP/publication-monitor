import json
import os
from pathlib import Path
import tempfile
import unittest

import publications as pub
import local_sources


class LocalSourcesTests(unittest.TestCase):
    def test_cache_new_exports_restart_and_invitation_markers(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            state = folder / 'state.json'
            data = {'papers': {}, 'invited': ['1'], 'new': [], 'known_ids': ['1']}
            csv = folder / 'publications_1.csv'
            csv.write_text('id;title\n1;Existing\n2;New\n')
            data, warnings = local_sources.refresh(state, data)
            self.assertEqual(warnings, [])
            self.assertEqual(data['new'], ['2'])
            self.assertEqual(data['invited'], ['1'])
            repeated, _ = local_sources.refresh(state, pub.load(state))
            self.assertEqual(repeated, data)
            newer = folder / 'publications_2.csv'
            newer.write_text('id;title\n1;Updated\n2;New\n3;Newest\n')
            stamp = csv.stat().st_mtime_ns + 1000000000
            os.utime(newer, ns=(stamp, stamp))
            updated, _ = local_sources.refresh(state, repeated)
            self.assertEqual(updated['new'], ['3'])
            self.assertEqual(updated['papers']['1']['title'], 'Updated')
            self.assertEqual(updated['invited'], ['1'])
            newer.write_text('bad csv')
            os.utime(newer, ns=(stamp+1000000000, stamp+1000000000))
            intact, warnings = local_sources.refresh(state, updated)
            self.assertTrue(warnings)
            self.assertEqual(intact, updated)
            self.assertEqual(json.loads(state.read_text()), updated)
