"""Restart Home snapshots are bounded display hints within the current owner."""
from pathlib import Path
import unittest
from tools.brightscript import run_function

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / 'source/core/HomeCachePolicy.brs'

class HomeCacheTests(unittest.TestCase):
    def project(self, rows):
        self.assertTrue(POLICY.is_file(), 'Home cache policy is missing')
        return run_function(POLICY, 'HomeCacheProjection', [rows])

    def test_snapshot_contains_only_first_visible_catalog_cards_and_volatile_downloads(self):
        cards = [{'itemId':str(i), 'title':'Film '+str(i), 'type':'movie',
                  'resumeMs':1000, 'watched':True, 'token':'secret',
                  'art':{'poster':'https://images.example.test/'+str(i)+'?signed=private'}} for i in range(9)]
        result = self.project([{'rowId':'recent', 'title':'Recently added', 'sectionType':'recently_added', 'items':cards}])
        self.assertEqual(6, len(result['row']['items']))
        self.assertEqual(6, len(result['downloads']))
        self.assertNotIn('private', str(result['row']))
        self.assertNotIn('secret', str(result['row']))
        self.assertNotIn('resumeMs', result['row']['items'][0])
        self.assertNotIn('watched', result['row']['items'][0])
        self.assertEqual('https://images.example.test/0?signed=private', result['downloads'][0]['url'])

if __name__ == '__main__':
    unittest.main()

class HomeCacheAdmissionTests(unittest.TestCase):
    def test_successful_empty_home_blocks_late_snapshot_and_scope_changes(self):
        scope = {'provider':'silo','sourceId':'silo:fixture','profileId':'p1','generation':3,'token':8}
        self.assertFalse(run_function(POLICY,'HomeCacheCanPublish',[scope,scope,8,True]))
        self.assertTrue(run_function(POLICY,'HomeCacheCanPublish',[scope,scope,8,False]))
        self.assertFalse(run_function(POLICY,'HomeCacheCanPublish',[scope,{**scope,'profileId':'p2'},8,False]))
        self.assertFalse(run_function(POLICY,'HomeCacheCanPublish',[scope,scope,9,False]))

    def test_personal_first_row_never_warms_offscreen_catalog(self):
        rows = [{'rowId':'resume','sectionType':'continue_watching','items':[]},
                {'rowId':'recent','sectionType':'recently_added','items':[{'itemId':'1','title':'Title','type':'movie','art':{}}]}]
        self.assertIsNone(run_function(POLICY,'HomeCacheProjection',[rows])['row'])


class HomeCacheImageTests(unittest.TestCase):
    def test_poster_dimensions_fit_the_same_budget_in_either_orientation(self):
        header = [137,80,78,71,13,10,26,10,0,0,0,13,73,72,68,82]
        for width, height, accepted in [(1000,1500,True), (1500,1000,True), (1200,1920,False)]:
            with self.subTest(width=width, height=height):
                image = header + list(width.to_bytes(4, 'big')) + list(height.to_bytes(4, 'big'))
                self.assertEqual(accepted, run_function(POLICY,'HomeCacheImageValid',[image]))

    def test_header_rejects_html_and_excessive_decoded_dimensions(self):
        small = [137,80,78,71,13,10,26,10,0,0,0,13,73,72,68,82,0,0,0,150,0,0,0,225]
        self.assertTrue(run_function(POLICY,'HomeCacheImageValid',[small]))
        excessive = small.copy(); excessive[18:20] = [16,0]
        self.assertFalse(run_function(POLICY,'HomeCacheImageValid',[excessive]))
        self.assertFalse(run_function(POLICY,'HomeCacheImageValid',[list(b'<html>not an image</html>')]))
