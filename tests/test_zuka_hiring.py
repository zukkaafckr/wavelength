import os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import zuka_hiring as h


def task(i, name, group, people):
    return {'id': i, 'name': name, 'group': group, 'people': people, 'text': [name], 'role': h._role({'name': name, 'text': [name]})}


class Hiring(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        os.environ['ATTICUS_DIR'] = self.d

    def test_nothing_is_silent_on_schedule_and_spoken_on_demand(self):
        snap = {'applied': [], 'assessments': []}
        self.assertEqual(h.speak(snap, new_only=True), '')
        self.assertIn('nobody in Applied', h.speak(snap, new_only=False, always=True))

    def test_new_names_role_and_assignee_then_not_repeated(self):
        snap = {'applied': [task('a1', 'Sam Lee - Junior Video Editor', 'APPLIED', ['Alex Ray'])],
                'assessments': [task('s1', 'Chris Poe - Static Designer', 'NEW TASK', [])]}
        out = h.speak(snap)
        self.assertIn('Sam Lee', out)
        self.assertIn('assigned to Alex', out)
        self.assertIn('not assigned to anyone yet', out)
        self.assertEqual(h.speak(snap), '')


if __name__ == '__main__':
    unittest.main()
