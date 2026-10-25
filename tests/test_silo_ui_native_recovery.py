"""Native failures retain the same private Silo lease and bounded attempt keys."""
from pathlib import Path
import unittest
import tempfile
import json
import xml.etree.ElementTree as ET
from tools.brightscript import run_function, run_brightscript
from tests.test_silo_playback_policy import plan, detail, SCOPE

ROOT = Path(__file__).resolve().parents[1]
FILES = [ROOT / 'source/core/SiloUIPlayerPolicy.brs', ROOT / 'source/core/SiloUIFormat.brs', ROOT / 'source/core/SiloPlaybackPolicy.brs']

class SiloUINativeRecovery(unittest.TestCase):
    def call(self, value=None, scope=None, position=12500, reason='decoder_failure'):
        return run_function(FILES, 'SiloUINativeRecoveryParams',
                            [plan() if value is None else value, SCOPE if scope is None else scope,
                             position, 'recover-request-0001', reason])

    def test_shipping_scene_can_resolve_native_version_fallback(self):
        scene = ET.parse(ROOT / 'components/SiloUIScene.xml').getroot()
        files = [ROOT / script.attrib['uri'].removeprefix('pkg:/')
                 for script in scene.findall('script')]
        value = plan()
        value['autoVersionRequest'] = {'itemId':'c1','fileId':'f1','autoVersion':True,
                                       'detail':detail(),'excludedVersionIds':[]}
        params = run_function(files, 'SiloUINativeVersionParams', [value, SCOPE, 12500])
        self.assertEqual(['f1'], params['excludedVersionIds'])
        self.assertEqual(12500, params['startPositionMs'])

    def test_shipping_scene_preserves_explicit_480p_during_native_recovery(self):
        scene = ET.parse(ROOT / 'components/SiloUIScene.xml').getroot()
        files = [ROOT / script.attrib['uri'].removeprefix('pkg:/')
                 for script in scene.findall('script')]
        value = plan()
        value['siloPlayback']['qualityPreference'] = '480p'
        value['siloPlayback']['availableQualities'].append(
            {'label':'480p','preservesSource':False,'height':480,'bitrateKbps':1500})
        for reason in ('decoder_failure', 'buffering_timeout'):
            with self.subTest(reason=reason):
                params = run_function(files, 'SiloUINativeRecoveryParams',
                                      [value, SCOPE, 12500, 'recover-request-0001', reason])
                self.assertIsNotNone(params, '480p must retain same-file recovery')
                self.assertEqual('480p', params['qualityPreference'])
                self.assertEqual('session-0001', params['sessionId'])
                self.assertEqual(12500, params['positionMs'])
                self.assertEqual(reason, params['failureClassification'])
                self.assertEqual(value, params['plan'])

    def test_shipping_scene_terminal_replan_retries_or_exits_without_crashing(self):
        scene = ET.parse(ROOT / 'components/SiloUIScene.xml').getroot()
        for alternate in (False, True):
            with self.subTest(alternate=alternate), tempfile.TemporaryDirectory() as directory:
                folder = Path(directory)
                files = []
                for script in scene.findall('script'):
                    source = ROOT / script.attrib['uri'].removeprefix('pkg:/')
                    if source.name in ('SiloUIPlayer.brs', 'SiloUIScene.brs'):
                        local = folder / source.name
                        local.write_text(source.read_text().replace('sub PlayerClose(', 'sub UnusedPlayerClose(',1)
                                         .replace('sub Api(', 'sub UnusedApi(',1).replace('sub PlayerShowFailure(', 'sub UnusedPlayerShowFailure(',1))
                        files.append(local)
                    else:
                        files.append(source)
                value = plan()
                if alternate:
                    value['autoVersionRequest'] = {'itemId':'c1','fileId':'f1','autoVersion':True,
                                                   'detail':detail(),'excludedVersionIds':[]}
                boundary = folder / 'boundary.brs'
                boundary.write_text('''sub PlayerShowFailure(stage as String, result as Dynamic)
 m.toast.text=SiloUIPlaybackFailureMessage(stage,result)
end sub
sub PlayerClose(finished as Boolean)
 m.closed = true
end sub
sub Api(action as String, params as Object, purpose as String, extra as Dynamic)
 m.sent.Push({action:action,params:params})
end sub
''')
                files.append(boundary)
                code = 'm.playPlan=ParseJson("' + json.dumps(value).replace('"','""') + '")\n'
                code += 'm.owner=ParseJson("' + json.dumps(SCOPE).replace('"','""') + '")\n'
                code += '''m.provider=m.owner.provider:m.sourceId=m.owner.sourceId:m.profileId=m.owner.profileId:m.generation=m.owner.generation
 m.view="player":m.playToken=5:m.playLastPositionMs=12500:m.recoveringNative=true:m.sent=[]
 m.video={position:0}:m.progressTimer={}:m.toast={}:m.toastTimer={}
 PlayerResult("play_recover",{ok:false,errorCode:"playback_terminal"},{},5)
 print FormatJson({closed:m.closed,sent:m.sent,message:m.toast.text})
'''
                result = json.loads(run_brightscript(files,code,root=folder).strip().splitlines()[-1])
                if alternate:
                    self.assertEqual('playback_start',result['sent'][0]['action'])
                    self.assertEqual(['f1'],result['sent'][0]['params']['excludedVersionIds'])
                    self.assertNotEqual(True,result['closed'])
                else:
                    self.assertTrue(result['closed'])
                    self.assertEqual([],result['sent'])
                    self.assertEqual('#3003: No further playback option is available. Choose another version or check server conversion settings.',result['message'])

    def test_request_retains_lease_position_tracks_and_quality(self):
        value = self.call()
        self.assertEqual('session-0001', value['sessionId'])
        self.assertEqual(12500, value['positionMs'])
        self.assertEqual('original', value['qualityPreference'])
        self.assertEqual('decoder_failure', value['failureClassification'])
        self.assertEqual(plan(), value['plan'])

    def test_stale_profile_source_file_or_session_never_recovers(self):
        for patch in ({'profileId': 'other'}, {'sourceId': 'silo:other'}):
            self.assertIsNone(self.call(scope={**SCOPE, **patch}))
        for field in ('sessionId', 'versionId'):
            value = plan()
            value[field] = 'other'
            self.assertIsNone(self.call(value=value))

    def test_exhausted_or_repeated_attempt_cannot_loop(self):
        value = plan()
        value['siloPlayback']['attemptCount'] = 8
        self.assertIsNone(self.call(value=value))
        value = plan()
        value['siloPlayback']['attemptedPlanKeys'] = [value['siloPlayback']['planAttemptKey']]
        self.assertIsNone(self.call(value=value))

    def test_invalid_position_or_reason_is_not_sent(self):
        for position in (-1, True, 'private'):
            self.assertIsNone(self.call(position=position))
        self.assertIsNone(self.call(reason='unknown'))
        self.assertEqual('buffering_timeout', self.call(reason='buffering_timeout')['failureClassification'])

    def test_exhausted_route_can_try_another_native_inventory_version(self):
        value = plan()
        value['siloPlayback']['attemptCount'] = 8
        value['autoVersionRequest'] = {'itemId':'c1','fileId':'f1','autoVersion':True,'detail':detail(),'excludedVersionIds':[]}
        params = run_function(FILES,'SiloUINativeVersionParams',[value,SCOPE,12500])
        self.assertEqual(['f1'], params['excludedVersionIds'])
        self.assertEqual(12500, params['startPositionMs'])
        self.assertIsNone(run_function(FILES,'SiloUINativeVersionParams',[plan(),SCOPE,12500]))
        self.assertIsNone(run_function(FILES,'SiloUINativeVersionParams',[value,{**SCOPE,'profileId':'other'},12500]))
        value['autoVersionRequest']['excludedVersionIds']=['f1']
        self.assertIsNone(run_function(FILES,'SiloUINativeVersionParams',[value,SCOPE,12500]))

    def test_alternate_version_keeps_verified_subtitle_off_intent(self):
        value=plan();value['siloPlayback']['subtitleOffRequired']=True
        value['autoVersionRequest']={'itemId':'c1','fileId':'f1','autoVersion':True,'detail':detail(),
                                     'excludedVersionIds':[],'subtitleMode':'auto','subtitleTrackId':'stale','subtitleTrackIndex':0}
        params=run_function(FILES,'SiloUINativeVersionParams',[value,SCOPE,12500])
        self.assertEqual('off',params['subtitleMode'])
        self.assertTrue(params['subtitleOffRequired'])
        self.assertNotIn('subtitleTrackId',params)
        self.assertNotIn('subtitleTrackIndex',params)

    def test_version_recovery_replaces_old_cut_markers_and_keeps_back_target(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            player=root/'player.brs'
            player.write_text((ROOT/'components/SiloUIPlayer.brs').read_text().replace('sub PlayerStart(', 'sub UnusedPlayerStart(',1).replace('sub PlayerReport(', 'sub UnusedPlayerReport(',1))
            boundary=root/'boundary.brs'
            boundary.write_text('''sub PlayerStart(plan as Object)
 m.markersAtStart=m.playMarkers
end sub
sub PlayerReport(action as String, positionMs=invalid as Dynamic, finalSample=invalid as Dynamic)
 m.stopped=m.playPlan.sessionId
end sub
''')
            result=run_brightscript([*FILES,ROOT/'components/SiloUISubtitleArtifact.brs',player,boundary],'''
 m.view="player":m.recoveringNative=true:m.playToken=5
 m.playPlan={sessionId:"old-lease"}:m.playMarkers=[{kind:"intro",startMs:0,endMs:60000}]
 m.progressSequence=11:m.playerReturn={view:"detail",zone:"detailButtons"}:m.savedCaptionMode="Off"
 PlayerResult("play_recover_version",{ok:true,plan:{sessionId:"new-lease"}},{effectiveMarkers:[{kind:"intro",startMs:1000,endMs:12000}]},5)
 print FormatJson({markers:m.markersAtStart,back:m.playerReturn,sequence:m.progressSequence,stopped:m.stopped})
''',root=root)
            value=json.loads(result.strip().splitlines()[-1])
            self.assertEqual(12000,value['markers'][0]['endMs'])
            self.assertEqual('detail',value['back']['view'])
            self.assertEqual(0,value['sequence'])
            self.assertEqual('old-lease',value['stopped'])

    def test_native_startup_without_a_buffering_event_still_reaches_its_deadline(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            player=root/'player.brs'
            player.write_text((ROOT/'components/SiloUIPlayer.brs').read_text().replace('sub PlayerClose(', 'sub UnusedPlayerClose(',1))
            boundary=root/'boundary.brs'
            boundary.write_text('''function SiloUIOwner() as Object
 return m.owner
end function
function SiloUICleanupUuid() as String
 return "recover-request-0001"
end function
sub Api(action as String,params as Object,purpose as String,extra as Dynamic)
 m.sent.Push(action)
end sub
sub Toast(message as String)
end sub
sub PlayerClose(finished as Boolean)
 m.closed=true
end sub
''')
            code='m.owner=ParseJson("'+json.dumps(SCOPE).replace('"','""')+'")\n'
            code+='m.playPlan=ParseJson("'+json.dumps(plan()).replace('"','""')+'")\n'
            code+='''m.view="player":m.playToken=4:m.playLastPositionMs=0:m.sent=[]
 m.video={state:"none",position:0}:m.progressTimer={}
 m.playWaitClock={TotalMilliseconds:function() as Integer
 return 120000
 end function}
 onProgressTimer()
 print FormatJson({sent:m.sent,recovering:m.recoveringNative})
'''
            result=json.loads(run_brightscript([*FILES,ROOT/'components/SiloUISubtitleArtifact.brs',player,boundary],code,root=root).strip().splitlines()[-1])
            self.assertEqual(['playback_replan'],result['sent'])
            self.assertTrue(result['recovering'])

    def test_native_error_replans_once_and_ignores_finished_while_pending(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            player = root / 'player.brs'
            player.write_text((ROOT / 'components/SiloUIPlayer.brs').read_text().replace(
                'sub PlayerClose(', 'sub UnusedPlayerClose(', 1))
            boundary = root / 'boundary.brs'
            boundary.write_text('''function SiloUIOwner() as Object
 return m.owner
end function
function SiloUICleanupUuid() as String
 return "recover-request-0001"
end function
sub Api(action as String, params as Object, purpose as String, extra as Dynamic)
 m.sent.Push({action:action,params:params,purpose:purpose,extra:extra})
end sub
sub Toast(text as String)
 m.message=text
end sub
sub PlayerClose(finished as Boolean)
 m.closed=true
end sub
''')
            code = 'm.owner=ParseJson("' + json.dumps(SCOPE).replace('"', '""') + '")\n'
            code += 'm.playPlan=ParseJson("' + json.dumps(plan()).replace('"', '""') + '")\n'
            code += '''m.view="player":m.playToken=4:m.playLastPositionMs=12500:m.sent=[]
 m.video={state:"error",position:0,errorCode:-3}:m.progressTimer={}
 onVideoState()
 m.video.state="finished"
 onVideoState()
 print FormatJson({requests:m.sent,recovering:m.recoveringNative,closed:m.closed,token:m.playToken})
'''
            value = json.loads(run_brightscript([*FILES, ROOT/'components/SiloUISubtitleArtifact.brs', ROOT/'components/SiloUICompatPlayback.brs', player, boundary], code, root=root).strip().splitlines()[-1])
            self.assertEqual(1, len(value['requests']))
            self.assertEqual('playback_replan', value['requests'][0]['action'])
            self.assertEqual(12500, value['requests'][0]['params']['positionMs'])
            self.assertTrue(value['recovering'])
            self.assertNotEqual(True, value.get('closed'))
            self.assertEqual(5, value['token'])

if __name__ == '__main__':
    unittest.main()
