"""Home Play resolves a series to its own episode before preparing a file."""
import unittest
from tests import test_silo_ui_playback_errors as errors


class SiloUISeriesPlayback(unittest.TestCase):
    def result(self, code):
        return errors.SiloUIPlaybackErrors().result(code)

    def test_series_play_uses_bounded_episode_resolver_instead_of_series_inventory(self):
        for kind in ('series','show'):
            with self.subTest(kind=kind):
                value=self.result('PlayItem({itemId:"series",type:"'+kind+'",title:"Show"},0)')
                self.assertEqual('playback_detail',value['sent'][0]['action'])
                self.assertEqual('play_target',value['sent'][0]['purpose'])
                self.assertEqual({'itemId':'series','type':kind},value['sent'][0]['params'])

    def test_own_episode_resolution_prepares_leaf_file_with_same_play_token(self):
        value=self.result('''PlayItem({itemId:"series",type:"series",title:"Show"},0)
 PlayerResult("play_target",{ok:true},{candidateItemId:"series",item:{itemId:"episode",type:"episode",seriesId:"series"},versions:[{versionId:"episode-file"}]},6)''')
        self.assertEqual(['playback_detail','playback_start'],[r['action'] for r in value['sent']])
        self.assertEqual('episode',value['sent'][1]['params']['itemId'])
        self.assertEqual('episode-file',value['sent'][1]['params']['fileId'])
        self.assertTrue(all(r['extra']==6 for r in value['sent']))

    def test_foreign_or_stale_resolution_never_starts_another_title(self):
        for candidate,parent,token in [('wrong','series',6),('series','wrong',6),('series','series',5)]:
            with self.subTest(candidate=candidate,parent=parent,token=token):
                value=self.result('''PlayItem({itemId:"series",type:"series",title:"Show"},0)
 PlayerResult("play_target",{ok:true},{candidateItemId:"'''+candidate+'''",item:{itemId:"episode",type:"episode",seriesId:"'''+parent+'''"},versions:[{versionId:"episode-file"}]},'''+str(token)+''')''')
                self.assertEqual(['playback_detail'],[r['action'] for r in value['sent']])
                if token==6:self.assertIn('#1002',value['message'])

    def test_detail_for_different_requested_item_cannot_replace_play_target(self):
        value=self.result('''PlayerResult("play_detail",{ok:true},{item:{itemId:"foreign"},versions:[{versionId:"foreign-file"}]},5)''')
        self.assertEqual([],value['sent'])
        self.assertIn('#1002',value['message'])

    def test_resolved_episode_uses_its_own_resume_position(self):
        value=self.result('''PlayItem({itemId:"series",type:"series",title:"Show",resumeMs:0},0)
 PlayerResult("play_target",{ok:true},{candidateItemId:"series",item:{itemId:"episode",type:"episode",seriesId:"series",resumeMs:45000},versions:[{versionId:"episode-file"}]},6)''')
        self.assertEqual(45000,value['sent'][-1]['params']['startPositionMs'])

    def test_resolved_empty_episode_gets_one_refresh_of_leaf_not_series(self):
        value=self.result('''PlayItem({itemId:"series",type:"series",title:"Show"},0)
 PlayerResult("play_target",{ok:true},{candidateItemId:"series",item:{itemId:"episode",type:"episode",seriesId:"series"},versions:[]},6)
 PlayerResult("play_detail",{ok:true},{item:{itemId:"episode",type:"episode",seriesId:"series"},versions:[]},6)''')
        self.assertEqual(['playback_detail','detail'],[r['action'] for r in value['sent']])
        self.assertEqual({'itemId':'episode'},value['sent'][1]['params'])
        self.assertIn('#1001',value['message'])


if __name__=='__main__':unittest.main()
