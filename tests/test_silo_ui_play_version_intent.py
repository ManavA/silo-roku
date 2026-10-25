"""Real PlayerInit/PlayItem version intent at the existing Scene/SG SDK seam.

All Scene scripts and playback-entry policy execute; SG nodes/tasks, device and
HTTP-agent leaves use the existing host bridge. No native playback is claimed.
"""
import json
import unittest
from unittest.mock import patch

from tests import test_silo_ui_native_hdr10_scene as scene
from tests import test_silo_ui_detail_audio as audio


class PlayVersionIntent(unittest.TestCase):
    def entry(self, code):
        execute = scene.run_brightscript
        choice = audio.choice()
        choice.update(itemId='fixture-item', sourceId='silo:https://silo.example',
                      profileId='fixture-owner', generation=7)
        encode = lambda value: json.dumps(value).replace('"', '""')
        setup = '''m.view="detail":m.detailToken=4
 m.detailVersions=ParseJson("''' + encode(audio.versions()) + '''")
 choice=ParseJson("''' + encode(choice) + '''")
 observations=[]:initialExplicit=m.playVersionExplicit
'''

        def launch(files, body, *, root):
            self.assertEqual(1, body.count('  PlayItem(item,0)'))
            body = body.replace('  PlayItem(item,0)', setup + code, 1)
            marker = 'print FormatJson({heroCandidateEligible:'
            self.assertEqual(1, body.count(marker))
            body = body.replace(marker, 'print FormatJson({initialExplicit:initialExplicit,observations:observations,versionExplicit:m.playVersionExplicit,selectedVersion:m.playSelectedVersion,token:m.playToken,heroCandidateEligible:', 1)
            return execute(files, body, root=root)

        with patch.object(scene, 'run_brightscript', side_effect=launch):
            return scene.OrdinaryNativeHdr10Scene().scene()

    def test_audio_only_pin_keeps_original_version_intent_automatic(self):
        result = self.entry('''PlayItem(item,0,"",choice)
 observations.Push({explicit:m.playVersionExplicit,selected:m.playSelectedVersion})
 PlayerResult("play_detail",{ok:true},{item:item,versions:m.detailVersions,markers:[]},m.playToken)
''')
        self.assertEqual([dict(explicit=False, selected='file-a')], result['observations'])
        self.assertIs(result['initialExplicit'], False)
        self.assertEqual(['detail', 'playback_start'], [task['job']['action'] for task in result['tasks']])
        params = {key.lower(): value for key, value in result['tasks'][-1]['job']['params'].items()}
        self.assertFalse(params['autoversion'])
        self.assertNotIn('playversionexplicit', params)
        self.assertEqual(('file-a', 'file:file-a:audio:1', 1),
                         (params['fileid'], params['audiotrackid'], params['audiotrackindex']))

    def test_explicit_version_with_audio_is_retained_and_next_audio_only_resets_it(self):
        result = self.entry('''PlayItem(item,0,"file-a",choice)
 observations.Push({explicit:m.playVersionExplicit,selected:m.playSelectedVersion,token:m.playToken})
 PlayItem(item,0,"",choice)
 observations.Push({explicit:m.playVersionExplicit,selected:m.playSelectedVersion,token:m.playToken})
''')
        self.assertEqual([dict(explicit=True, selected='file-a', token=1),
                          dict(explicit=False, selected='file-a', token=2)], result['observations'])
        self.assertEqual(['detail', 'detail'], [task['job']['action'] for task in result['tasks']])

    def test_rejected_audio_choice_preserves_the_active_version_intent(self):
        result = self.entry('''PlayItem(item,0,"file-a",choice)
 observations.Push({explicit:m.playVersionExplicit,selected:m.playSelectedVersion,token:m.playToken})
 stale=ParseJson(FormatJson(choice)):stale.visit=3
 PlayItem(item,0,"",stale)
 observations.Push({explicit:m.playVersionExplicit,selected:m.playSelectedVersion,token:m.playToken})
''')
        expected = dict(explicit=True, selected='file-a', token=1)
        self.assertEqual([expected, expected], result['observations'])
        self.assertEqual(['detail'], [task['job']['action'] for task in result['tasks']])
