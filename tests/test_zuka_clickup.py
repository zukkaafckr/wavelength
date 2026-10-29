import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import zuka_apps as apps  # noqa: E402
import zuka_clickup as cu  # noqa: E402

ASSIGNED = ['Ad LEARNINGS', 'Current status: learnings', 'The Night Shift Story', '@Sam Rivers — assigned to you. Edit it.', 'Oct 26', '4', 'unread notifications']
STATUS = ['Ad LOSER', 'Current status: loser', 'The Chain', 'Alex Kim changed status:', 'Approved', 'Learnings', '4:05 PM', '1', 'unread notification']
BOT = ['Ad LOSER', 'Current status: loser', 'OLD CONCEPT', 'Chris Lee assigned this task to you', 'Sep 9', '22', 'unread notifications']
READ = ['Ad WINNER', 'Current status: winner', 'Quiet One', '@Sam Rivers', 'fb.mefb.me', 'Yesterday']
DATA = {'tab': 'Primary\n54 unread', 'rows': [ASSIGNED, STATUS, BOT, READ, ['junk', 'no status here']]}


class Bridge(unittest.TestCase):
    def test_bundle_assigned(self):
        i = cu.parse_bundle(ASSIGNED)
        self.assertEqual((i['task'], i['status'], i['date'], i['count']), ('The Night Shift Story', 'learnings', 'Oct 26', 4))
        self.assertTrue(i['assigned']); self.assertEqual(i['mentions'], ['Sam Rivers'])

    def test_time_becomes_today_and_message_joined(self):
        i = cu.parse_bundle(STATUS)
        self.assertEqual((i['date'], i['count'], i['message']), ('Today', 1, 'Alex Kim changed status: Approved Learnings'))
        self.assertFalse(i['assigned'])

    def test_who_and_noise_and_no_count(self):
        self.assertEqual(cu.parse_bundle(BOT)['who'], 'Chris Lee')
        r = cu.parse_bundle(READ)
        self.assertEqual((r['message'], r['count'], r['date']), ('@Sam Rivers', 0, 'Yesterday'))

    def test_unparseable_is_skipped(self):
        self.assertIsNone(cu.parse_bundle(['x']))
        items, unread = cu.parse_inbox(DATA)
        self.assertEqual([i['task'] for i in items], ['The Night Shift Story', 'The Chain', 'OLD CONCEPT', 'Quiet One'])
        self.assertEqual(unread, 54)

    def test_same_shape_as_old_reader(self):
        old = apps.parse_clickup_inbox('Primary 54 unread\nChange status Current status: learnings The Night Shift Story @Sam Rivers — assigned to you. Edit it. Oct 26 4 unread notifications\nThe Night Shift Story\nCurrent status: learnings\n')
        self.assertEqual(set(cu.parse_bundle(ASSIGNED)), set(old[0]))

    def test_board_mine(self):
        rows = [{'name': 'The Green Lie', 'group': 'IN PROGRESS', 'people': ['Alex Kim', 'Sam Rivers']},
                {'name': 'Fresh Script', 'group': 'IN REVIEW', 'people': []}]
        b = cu.parse_board(rows, 'sam')
        self.assertEqual([(t['name'], t['mine']) for t in b], [('The Green Lie', True), ('Fresh Script', False)])
        self.assertEqual(set(b[0]), {'name', 'group', 'people', 'mine'})


class Fallback(unittest.TestCase):
    def test_bridge_none_uses_accessibility_reader(self):
        with mock.patch.object(cu, 'clickup_snapshot_bridge', return_value=None), mock.patch.object(apps, 'read_app', return_value=None) as ra:
            self.assertIsNone(apps.clickup_snapshot('Sam'))
        ra.assert_called_once()

    def test_bridge_result_wins(self):
        snap = {'inbox': [], 'unread': 1, 'board': [], 'team': '1'}
        with mock.patch.object(cu, 'clickup_snapshot_bridge', return_value=snap), mock.patch.object(apps, 'read_app', side_effect=AssertionError):
            self.assertEqual(apps.clickup_snapshot('Sam'), snap)

    def test_no_bridge_port_returns_none(self):
        with mock.patch.object(cu.cdp, 'port_open', return_value=False), mock.patch.object(cu.hiring, '_locked', return_value='/nonexistent'):
            self.assertIsNone(cu.clickup_snapshot_bridge('Sam'))


if __name__ == '__main__':
    unittest.main()
