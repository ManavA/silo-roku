"""Explicit audio preferences use catalog identity and profile-scoped v2 writes."""
import json
from pathlib import Path
import tempfile
import unittest
from tools.brightscript import run_function, run_brightscript
from test_silo_adapter import SESSION
ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT/'source/adapters/SiloAdapter.brs'
POLICY = ROOT/'source/core/SiloUIPlaybackChoicesPolicy.brs'

class AudioPreferenceTests(unittest.TestCase):
    def test_write_uses_profile_escaped_key_and_empty_204(self):
        body = {'audio_track_index':1,'track_signature':{'codec':'ac3'}}
        request = run_function(ADAPTER,'BuildSiloRequest',['audio_pref_set',SESSION,{'seriesId':'series/a b','preference':body}])
        self.assertTrue(request['ok'])
        self.assertEqual(request['method'],'PUT')
        self.assertEqual(request['url'],'https://silo.example/api/v2/audio-prefs/series%2Fa%20b')
        self.assertEqual(request['headers']['X-Profile-Id'],'p1')
        self.assertEqual(json.loads(request['body']),body)
        result = run_function(ADAPTER,'DecodeSiloResponse',['audio_pref_set','',{'statusCode':204}])
        self.assertTrue(result['ok'])

    def test_signature_preserves_raw_titles_and_array_ordinal(self):
        tracks = run_function(ADAPTER,'SiloTracks',[[{'index':87,'title':'','embedded_title':' Surround ','language':' eng ','codec':' ac3 ','layout':' 5.1 ','channels':6,'default':True}],True])
        result = run_function(ADAPTER,'SiloAudioPreference',[{'itemId':'ep','type':'episode','seriesId':'series'},'file',0,[{'versionId':'file','audioTracks':tracks}]])
        self.assertEqual(result,{'seriesId':'series','preference':{'audio_track_index':0,'audio_language':'eng','track_signature':{'language':'eng','title':'','embedded_title':'Surround','codec':'ac3','layout':'5.1','channels':6}}})
        movie = run_function(ADAPTER,'SiloAudioPreference',[{'itemId':'movie','type':'movie','seriesId':'wrong'},'file',0,[{'versionId':'file','audioTracks':tracks}]])
        self.assertEqual(movie['seriesId'],'movie')
        self.assertIsNone(run_function(ADAPTER,'SiloAudioPreference',[{'itemId':'ep','type':'episode'},'file',0,[{'versionId':'file','audioTracks':tracks}]]))

    def coordinator(self, body):
        with tempfile.TemporaryDirectory() as directory:
            boundary=Path(directory)/'boundary.brs'
            boundary.write_text('''sub PlayerStart(plan as Object)
 if m.rejectBind=true then return
 m.playPlan=plan:m.bound=true
end sub
sub PlayerRestorePausedIntent()
end sub
sub PlayerClose(finished as Boolean)
 m.closed=true
end sub
sub Toast(message as String)
 m.message=message
end sub
function SiloUIOwner() as Object
 return {provider:m.provider,sourceId:m.sourceId,profileId:m.profileId,generation:m.generation}
end function
sub ApiOwned(action as String,params as Object,purpose as String,extra as Dynamic,owner as Object)
 m.sent.Push({action:action,params:params,extra:extra,owner:owner,bound:m.bound})
end sub
''')
            scene=Path(directory)/'scene.brs'
            scene.write_text((ROOT/'components/SiloUIScene.brs').read_text().replace('sub ApiOwned(', 'sub UnusedApiOwned(',1).replace('sub Toast(', 'sub UnusedToast(',1))
            return json.loads(run_brightscript([ADAPTER,ROOT/'source/core/SiloPlaybackPolicy.brs',ROOT/'components/SiloUIPlaybackChoices.brs',scene,boundary],'''
 m.provider="silo":m.sourceId="silo:one":m.profileId="p1":m.generation=1:m.sent=[]
 m.playPlan={provider:"silo",sourceId:"silo:one",itemId:"ep",versionId:"file",siloPlayback:{selectedTracks:{audio:{id:"file:file:audio:87",index:87}}}}
 pref={seriesId:"series",preference:{audio_track_index:0,track_signature:{codec:"ac3"}}}
 '''+body,root=Path(directory)).strip().splitlines()[-1])

    def test_save_is_serialized_latest_choice_wins_and_stale_scope_drops(self):
        result=self.coordinator('''
 PlaybackRememberAudio(pref,87)
 first=m.sent[0].extra
 pref.preference.audio_track_index=1
 PlaybackRememberAudio(pref,87)
 pref.preference.audio_track_index=2
 PlaybackRememberAudio(pref,87)
 before=m.sent.Count()
 PlaybackAudioPreferenceResult(first)
 second=m.sent[1].extra
 pref.preference.audio_track_index=3
 PlaybackRememberAudio(pref,87)
 m.generation=2
 PlaybackAudioPreferenceResult(second)
 print FormatJson({before:before,count:m.sent.Count(),last:m.sent[1].params.preference.audio_track_index})
 ''')
        self.assertEqual(result,{'before':1,'count':2,'last':2})

    def test_detail_explicit_success_saves_after_binding_and_failures_do_not(self):
        from test_silo_ui_detail_audio import SiloUIDetailAudio
        fixture=SiloUIDetailAudio()
        boundary='''sub PlaybackRememberAudio(preference as Dynamic,index as Dynamic)
 m.saved={bound:m.promoted,index:index,preference:preference}
end sub
'''
        for explicit,success in [(True,True),(False,True),(True,False)]:
            result=fixture.player('''
 m.playAudioChoice=selected
 EXPLICIT
 m.playItem=m.detailItem:m.playVersions=m.detailVersions
 m.view="player"
 m.playPlan={itemId:"movie",versionId:"file-a"}
 PlayerResult("play_start",{ok:SUCCESS,plan:{url:"https://example.invalid/media"},audioPreference:{seriesId:"movie",preference:{audio_track_index:1}}},{},m.playToken)
 print FormatJson({saved:m.saved})
 '''.replace('EXPLICIT','' if explicit else 'm.playAudioChoice=invalid').replace('SUCCESS','true' if success else 'false'),boundary_extra=boundary)
            if explicit and success:
                self.assertTrue(result['saved']['bound'])
                self.assertEqual(result['saved']['index'],1)
            else:
                self.assertIsNone(result['saved'])

    def test_wrong_receipt_and_missing_authority_cannot_save(self):
        self.assertEqual(self.coordinator('''
 PlaybackRememberAudio(invalid,87)
 PlaybackRememberAudio(pref,1)
 m.playPlan.versionId="different"
 PlaybackRememberAudio(pref,87)
 print FormatJson(m.sent.Count())
 '''),0)

    def test_source_replan_saves_once_after_success_and_failure_saves_zero(self):
        for success in (True,False):
            result=self.coordinator('''
 m.view="player":m.playToken=1:m.video={}:m.trackPref={}:m.trackPrefLanes={}
 m.playPlan.sessionId="lease":m.playPlan.planId="old":m.playPlan.cleanupOwner=SiloUIOwner()
 nextPlan=ParseJson(FormatJson(m.playPlan)):nextPlan.planId="new"
 extra={token:1,sessionId:"lease",planId:"old",paused:false,language:"eng",name:"English",selectedIndex:87}
 PlaybackAudioResult({ok:SUCCESS,plan:nextPlan,audioPreference:pref},extra)
 print FormatJson({count:m.sent.Count(),bound:m.bound})
 '''.replace('SUCCESS','true' if success else 'false'))
            self.assertEqual(result['count'],1 if success else 0)
            if success:
                self.assertTrue(result['bound'])

    def test_save_acknowledgement_does_not_change_playback(self):
        result=self.coordinator('''
 PlaybackRememberAudio(pref,87)
 savedPlan=FormatJson(m.playPlan)
 PlaybackAudioPreferenceResult(m.sent[0].extra)
 print FormatJson({same:FormatJson(m.playPlan)=savedPlan,count:m.sent.Count(),flight:m.audioPreferenceFlight})
 ''')
        self.assertEqual(result,{'same':True,'count':1,'flight':None})

    def test_unsupported_http_and_auth_errors_are_best_effort(self):
        for status,error in [(404,'not_found'),(405,'http_error'),(501,'http_error'),(401,'auth_required')]:
            result=self.coordinator('''
 PlaybackRememberAudio(pref,87)
 savedPlan=FormatJson(m.playPlan)
 task={unobserveField:sub(field as String)
 end sub}
 m.pending={"7":{purpose:"audio_preference",task:task,extra:m.sent[0].extra,generation:1}}
 event={data:{requestId:7,ok:false,statusCode:STATUS,errorCode:"ERROR"},getData:function()
 return m.data
 end function}
 onApiResult(event)
 print FormatJson({same:FormatJson(m.playPlan)=savedPlan,count:m.sent.Count(),flight:m.audioPreferenceFlight,pending:m.pending.Count()})
 '''.replace('STATUS',str(status)).replace('ERROR',error))
            self.assertEqual(result,{'same':True,'count':1,'flight':None,'pending':0})

    def test_rejected_binding_cannot_save_against_old_plan(self):
        result=self.coordinator('''
 m.view="player":m.playToken=1:m.video={}:m.trackPref={}:m.trackPrefLanes={}:m.rejectBind=true
 m.playPlan.sessionId="lease":m.playPlan.planId="old":m.playPlan.cleanupOwner=SiloUIOwner()
 nextPlan=ParseJson(FormatJson(m.playPlan)):nextPlan.planId="new"
 extra={token:1,sessionId:"lease",planId:"old",paused:false,language:"eng",name:"English",selectedIndex:87}
 PlaybackAudioResult({ok:true,plan:nextPlan,audioPreference:pref},extra)
 print FormatJson({count:m.sent.Count(),planId:m.playPlan.planId})
 ''')
        self.assertEqual(result,{'count':0,'planId':'old'})
