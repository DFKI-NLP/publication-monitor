import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import scheduled


class ScheduleTests(unittest.TestCase):
    def test_evening_only_queues_morning_only_sends_once(self):
        with tempfile.TemporaryDirectory() as folder:
            state=Path(folder)/'known.json';state.write_text('[1]')
            paper={'title':'New paper','author':'Example','id':'2'}
            invitations=[{'name':'Example','email':'ex01@dfki.de','papers':{2:paper}}]
            with patch.object(scheduled.monitor,'fetch_publications',return_value={1:{'title':'Old'},2:paper}) as fetch,patch.object(scheduled.monitor,'plan_invitations',return_value=(invitations,[])),patch.object(scheduled.monitor,'send_email') as mail:
                scheduled.run('prepare',state)
                mail.assert_not_called();fetch.assert_called_once()
                self.assertEqual(json.loads(state.read_text()),[1,2])
            with patch.object(scheduled.monitor,'fetch_publications',side_effect=AssertionError('Morning must not fetch')),patch.object(scheduled.monitor,'send_email') as mail:
                scheduled.run('send',state)
                self.assertEqual([c.args[2] for c in mail.call_args_list],[['ex01@dfki.de'],['colloquium-slt@dfki.de']])
                mail.reset_mock();scheduled.run('send',state);mail.assert_not_called()

    def test_crash_between_queue_and_state_does_not_duplicate(self):
        with tempfile.TemporaryDirectory() as folder:
            state=Path(folder)/'known.json';state.write_text('[1]')
            with patch.object(scheduled.monitor,'fetch_publications',return_value={1:{},2:{}}),patch.object(scheduled.monitor,'plan_invitations',return_value=([],[])) as plan:
                with patch.object(scheduled.monitor,'save_state',side_effect=OSError('dummy')):
                    with self.assertRaises(OSError):scheduled.run('prepare',state)
                scheduled.run('prepare',state)
                plan.assert_called_once()
                self.assertEqual(len(list((Path(folder)/'invitation-queue').glob('*.json'))),1)

    def test_interrupted_send_is_not_repeated(self):
        with tempfile.TemporaryDirectory() as folder:
            queue=Path(folder)
            scheduled.save(queue/'batch.json',{'ids':[2],'invitations':[{'name':'Example','email':'ex01@dfki.de','papers':{},'status':'sending'}],'skipped':[],'digest':'pending'})
            with patch.object(scheduled.monitor,'send_email') as mail:
                with self.assertRaises(RuntimeError):scheduled.send(queue)
                self.assertEqual([c.args[2] for c in mail.call_args_list],[['colloquium-slt@dfki.de']])


if __name__=='__main__':unittest.main()
