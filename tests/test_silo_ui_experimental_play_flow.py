"""Explicit original experiments retain detail consent without changing normal Play."""
import json
import unittest
from tests import test_silo_ui_detail_audio as audio
from tests import test_silo_original_p8_policy as p8


def setup():
    rows=audio.versions()
    rows[0].update(container='mkv',videoCodec='hevc',hdr=True,
                   videoTracks=[p8.SiloOriginalP8PolicyTests().fixture()['freshFile']['wire']['video_tracks'][0]])
    return 'm.detailVersions=ParseJson("'+json.dumps(rows).replace('"','""')+'")\n'+'''
 m.detailSelectedVersion="file-a":m.detailAudioChoice=selected
 ticket={kind:"experimental_original",visit:4,sourceId:"silo:one",profileId:"profile",generation:2,itemId:"movie",fileId:"file-a",audioSignature:FormatJson(selected)}
'''


class ExperimentalPlayFlow(unittest.TestCase):
    def scene(self, code, boundary_extra=""):
        return audio.SiloUIDetailAudio().player(setup()+code,boundary_extra=boundary_extra)

    def test_explicit_action_bypasses_prebuffer_pins_4k_and_uses_ephemeral_original_off(self):
        result=self.scene('''m.preferences={quality:"720p",subtitles:"always"}
 m.prebuf={ready:true,itemId:"movie",startMs:0,item:{itemId:"movie"},plan:{}}
 PlayItem(m.detailItem,12500,"file-a",selected,ticket)
 PlayerResult("play_detail",{ok:true},{item:m.detailItem,versions:m.detailVersions},m.playToken)
 print FormatJson({requests:m.sent,promoted:m.promoted,prefs:m.preferences})''')
        self.assertFalse(result['promoted'])
        self.assertEqual('detail',result['requests'][0]['action'])
        params={k.lower():v for k,v in result['requests'][1]['params'].items()}
        self.assertTrue(params['experimentaloriginal'])
        self.assertFalse(params['autoversion'])
        self.assertEqual(('file-a','original','off',12500),
                         (params['fileid'],params['qualitypreference'],params['subtitlemode'],params['startpositionms']))
        self.assertEqual(dict(quality='720p',subtitles='always'),result['prefs'])


    def test_changed_intent_before_fresh_detail_never_allocates(self):
        for change in ('m.detailToken=5','m.detailSelectedVersion="other"','m.detailAudioChoice=invalid','m.generation=3'):
            with self.subTest(change=change):
                result=self.scene('''PlayItem(m.detailItem,0,"file-a",selected,ticket)
'''+change+'''
 PlayerResult("play_detail",{ok:true},{item:m.detailItem,versions:m.detailVersions},m.playToken)
 print FormatJson({count:m.sent.Count(),loading:m.playLoading})''')
                self.assertEqual(1,result['count'])
                self.assertFalse(result['loading'])

    def test_normal_next_play_does_not_inherit_experiment(self):
        result=self.scene('''PlayItem(m.detailItem,0,"file-a",selected,ticket)
 PlayerCancelPreparation()
 PlayItem(m.detailItem,0,"file-a",selected)
 PlayerResult("play_detail",{ok:true},{item:m.detailItem,versions:m.detailVersions},m.playToken)
 print FormatJson({params:m.sent[2].params,choice:m.playExperimentalChoice})''')
        self.assertIsNone(result['choice'])
        self.assertNotIn('experimentaloriginal',{k.lower():v for k,v in result['params'].items()})

    def test_changed_intent_after_allocation_is_cleaned_without_native_start(self):
        result=self.scene('''PlayItem(m.detailItem,0,"file-a",selected,ticket)
 PlayerResult("play_detail",{ok:true},{item:m.detailItem,versions:m.detailVersions},m.playToken)
 m.detailAudioChoice=invalid
 PlayerResult("play_start",{ok:true,plan:{url:"https://media.invalid/file",experimentalOriginal:true,sessionId:"lease",stopId:"stop-1",cleanupOwner:{provider:"silo",sourceId:"silo:one",profileId:"profile",generation:2,sessionRevision:1}}},{},m.playToken)
 print FormatJson({promoted:m.promoted,cleaned:m.cleaned,loading:m.playLoading})''',boundary_extra='''
 sub ApiOwned(action as String,params as Object,purpose as String,extra as Dynamic,owner as Object)
  if action="playback_stop" then m.cleaned=true
 end sub
''')
        self.assertFalse(result['promoted'])
        self.assertTrue(result['cleaned'])
        self.assertFalse(result['loading'])

    def test_experimental_native_failure_never_replans_or_changes_version(self):
        result=self.scene('''m.view="player":m.playPlan={experimentalOriginal:true}
 print FormatJson({replan:PlayerRecoverNativeFailure("error"),version:PlayerRecoverNativeVersion(),requests:m.sent})''')
        self.assertFalse(result['replan'])
        self.assertFalse(result['version'])
        self.assertEqual([],result['requests'])


    def test_experiment_refuses_subtitle_change_without_mutating_preferences(self):
        result=self.scene('''m.view="player":m.playPlan={experimentalOriginal:true}
 m.trackDialog={visible:true}:m.trackList={itemSelected:0}
 m.trackChoices=[{kind:"subtitle",language:"eng",name:"English",trackId:"s1"}]
 m.trackPref={subtitle:"spa"}:m.video={globalCaptionMode:"Off"}
 onPlayerTrackChoice()
 print FormatJson({pref:m.trackPref.subtitle,caption:m.video.globalCaptionMode,message:m.message})''')
        self.assertEqual('spa',result['pref'])
        self.assertEqual('Off',result['caption'])
        self.assertIn('off',result['message'].lower())


if __name__=='__main__':unittest.main()
