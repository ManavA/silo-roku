"""Authorized seam: selected source descriptor + native events -> commands.
Host tests prove ownership/refusal/timing policy, not native metadata semantics.
"""
import unittest
from pathlib import Path
from tools.brightscript import run_function
ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / 'source/core/SiloUIOriginalPlaybackPolicy.brs'

def descriptor():
    return dict(schemaVersion=1, sourceId='silo:test', itemId='item-1', fileId='file-1',
                sessionId='session-1', planId='plan-1', playbackAttemptId='attempt-1',
                outputFingerprint='output-1', scope={'profileId':'profile-1'}, guarded=True,
                mappingMode='structured_format',
                audioIdentity=dict(index=1,id='opaque-audio-1',codec='ac3',language='en',channels=6,layout='5.1'),
                sourceAudio=[dict(index=0,codec='truehd',language='en',channels=8,layout='7.1'),
                             dict(index=1,codec='ac3',language='en',channels=6,layout='5.1')])

def inventory():
    return [dict(Track='native-random-9',Format='ac3',Language='eng',Name='Untrusted title'),
            dict(Track='native-random-2',Format='truehd',Language='eng',Name='AC3')]

class OriginalPlayback(unittest.TestCase):
    def create(self, proof=None):
        return run_function([POLICY], 'SiloUIOriginalCreate', [descriptor() if proof is None else proof, 7, 3, 0])
    def event(self, state, kind, **values):
        return run_function([POLICY], 'SiloUIOriginalReduce', [state, dict(kind=kind,token=7,generation=3,nowMs=1000,**values)])
    def test_scrambled_inventory_selects_actual_handle_from_structured_format(self):
        result = self.event(self.create(), 'inventory', inventory=inventory())
        self.assertEqual({'kind':'select','trackId':'native-random-9'}, result['command'])
        self.assertEqual('selected', result['state']['phase'])
        self.assertIsNone(self.event(result['state'], 'inventory', inventory=inventory())['command'])
        replacement = inventory()
        replacement[0]['Track'] = 'replacement-handle'
        changed = self.event(result['state'], 'inventory', inventory=replacement)
        self.assertEqual({'kind':'select','trackId':'replacement-handle'},changed['command'])
        old_readback = self.event(changed['state'],'observation',nativeState='playing',positionMs=2100,audioTrack='native-random-9',audioFormat='ac3')
        self.assertEqual('selected',old_readback['state']['phase'])
    def test_ambiguous_missing_or_misleading_inventory_recovers_once(self):
        variants = [inventory()+[dict(Track='commentary',Format='ac3',Language='eng')],
                    [dict(Track='misleading',Name='English AC3',Language='eng')],
                    [dict(Track='duplicate',Format='ac3',Language='eng'),dict(Track='duplicate',Format='truehd',Language='eng')]]
        for raw in variants:
            with self.subTest(raw=raw):
                result = self.event(self.create(), 'inventory', inventory=raw)
                self.assertEqual('recover', result['command']['kind'])
                self.assertEqual('recovering', result['state']['phase'])
                self.assertIsNone(self.event(result['state'], 'inventory', inventory=raw)['command'])
    def test_selection_requires_fresh_playing_codec_readback_and_advancing_position(self):
        state = self.event(self.create(), 'inventory', inventory=inventory())['state']
        for values in [dict(nativeState='buffering',positionMs=100,audioFormat='ac3',audioTrack='native-random-9'),
                       dict(nativeState='playing',positionMs=100,audioFormat='truehd',audioTrack='native-random-9'),
                       dict(nativeState='playing',positionMs=100,audioFormat='ac3',audioTrack='native-random-2')]:
            state = self.event(state, 'observation', **values)['state']
            self.assertEqual('selected', state['phase'])
        state = self.event(state, 'observation', nativeState='playing',positionMs=100,audioFormat='ac3',audioTrack='native-random-9')['state']
        self.assertEqual('selected', state['phase'])
        state = self.event(state, 'observation', nativeState='playing',positionMs=1100,audioFormat='ac3',audioTrack='native-random-9')['state']
        self.assertEqual('verified_playing', state['phase'])
    def test_start_budget_cannot_be_reset_by_buffering_or_inventory_churn(self):
        state = self.create()
        for now in (5000,15000,29999,30000):
            result = run_function([POLICY], 'SiloUIOriginalReduce', [state,dict(kind='observation',token=7,generation=3,nowMs=now,nativeState='buffering')])
            state = result['state']
        self.assertEqual({'kind':'recover','reason':'startup_timeout'}, result['command'])

    def test_stale_events_and_cancel_cannot_select_or_recover(self):
        state = self.create()
        for patch in ({'token':6},{'generation':2}):
            result = run_function([POLICY], 'SiloUIOriginalReduce', [state,dict(kind='inventory',token=7,generation=3,nowMs=31000,inventory=inventory()) | patch])
            self.assertEqual(state,result['state'])
            self.assertIsNone(result['command'])
        closed = self.event(state,'cancel')['state']
        self.assertEqual('closed',closed['phase'])
        self.assertIsNone(self.event(closed,'inventory',inventory=inventory())['command'])

    def test_early_finish_and_inventory_loss_never_complete(self):
        state = self.event(self.create(),'inventory',inventory=inventory())['state']
        for kind, values in [('observation',{'nativeState':'finished'}),('inventory',{'inventory':[]})]:
            result = self.event(state,kind,**values)
            self.assertEqual('recover',result['command']['kind'])
    def test_foreground_namespace_forwards_normalized_local_subtitle_intent(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            boundary = Path(directory)/'boundary.brs'
            boundary.write_text('''sub Api(action as String,params as Object,purpose as String,extra as Dynamic)
 m.sent={action:action,params:params,purpose:purpose}
end sub
function ForegroundSubtitleIntent(mode as String) as Object
 m.playClock={TotalMilliseconds:function() as Integer
  return 0
 end function}
 m.playToken=7:m.playSelectedVersion="":m.playStartMs=0:m.provider="silo":m.preferences={subtitles:mode}
 m.playItem={itemId:"fixture-item"}
 data={item:{itemId:"fixture-item"},versions:[{versionId:"731"}],markers:[]}
 PlayerResult("play_detail",{ok:true},data,7)
 return m.sent
end function
''')
            files=[ROOT/'components/SiloUIPlayer.brs',ROOT/'source/core/SiloUISettingsPolicy.brs',ROOT/'source/core/SiloUIDetailPolicy.brs',ROOT/'source/core/SiloUIFormat.brs',boundary]
            for mode in ['off','always','auto']:
                sent=run_function(files,'ForegroundSubtitleIntent',[mode],root=Path(directory))
                self.assertEqual(mode,sent['params'].get('subtitlemode'),sent)
                self.assertNotIn('subtitletrackindex',sent['params'])
                self.assertEqual('playback_start',sent['action'])

    def test_shipping_callback_preserves_guarded_audio_and_subtitle_preferences(self):
        import json
        import tempfile
        from tools.brightscript import run_brightscript
        with tempfile.TemporaryDirectory() as directory:
            boundary = Path(directory)/'boundary.brs'
            boundary.write_text('''function TrackPreferenceInventory(raw as Dynamic,kind as String) as Object
 return [{trackId:"wrong-native",language:"en",name:"Main"}]
end function
function TrackPreferenceLaneScore(track as Object,kind as String,wanted as String) as Integer
 return 0
end function
''')
            result = json.loads(run_brightscript([POLICY,ROOT/'components/SiloUISubtitleArtifact.brs',ROOT/'components/SiloUIPlayer.brs',boundary],'''
 m.view="player":m.playPlan={}:m.trackPref={audio:"en",subtitle:"off"}:m.trackPrefLanes={}
 m.originalPlayback={phase:"selected"}
 m.video={audioTrack:"owned-native",availableAudioTracks:[],availableSubtitleTracks:[],globalCaptionMode:"On"}
 onPlayerTracks()
 print FormatJson({audio:m.video.audioTrack,captions:m.video.globalCaptionMode})
''',root=Path(directory)).strip())
        self.assertEqual({'audio':'owned-native','captions':'Off'},result)
    def test_structured_dolby_digital_alias_and_same_codec_source_ambiguity(self):
        raw = [dict(Track='handle-7',Format='Dolby Digital',Language='eng')]
        result = self.event(self.create(),'inventory',inventory=raw)
        self.assertEqual('handle-7',result['command']['trackId'])
        proof = descriptor()
        proof['sourceAudio'][0].update(codec='ac3',channels=2)
        result = self.event(self.create(proof),'inventory',inventory=raw)
        self.assertEqual('recover',result['command']['kind'])

    def test_observed_native_mat_is_known_nonselectable_and_name_is_ignored(self):
        raw = [dict(Track='native-mat',Format='dolby metadata-enhanced audio transmission',Language='eng',Name='Dolby Digital AC3'),
               dict(Track='native-ac3',Format='dolby digital',Language='eng',Name='TrueHD')]
        result = self.event(self.create(),'inventory',inventory=raw)
        self.assertEqual({'kind':'select','trackId':'native-ac3'},result['command'])
        raw[0]['Format'] = 'unclassified transport'
        self.assertEqual('recover',self.event(self.create(),'inventory',inventory=raw)['command']['kind'])
        proof = descriptor()
        proof['audioIdentity'].update(codec='dolby metadata-enhanced audio transmission')
        proof['sourceAudio'][1].update(codec='dolby metadata-enhanced audio transmission')
        self.assertIsNone(self.create(proof))

    def test_observed_native_aac_description_is_not_a_source_codec_alias(self):
        proof = descriptor()
        proof['sourceAudio'][0].update(codec='aac',channels=2,layout='stereo')
        label = 'ISO/IEC 14496-3, Advanced Audio Coding, ASC header'
        raw = [dict(Track='native-aac',Format=label,Language='eng',Name='AC-3 5.1'),
               dict(Track='native-ac3',Format='Dolby Digital',Language='eng',Name='AAC 2.0')]
        result = self.event(self.create(proof),'inventory',inventory=raw)
        self.assertEqual({'kind':'select','trackId':'native-ac3'},result['command'])
        proof['audioIdentity'].update(codec=label)
        proof['sourceAudio'][1].update(codec=label)
        self.assertIsNone(self.create(proof))

    def test_descriptor_requires_complete_identity_and_bounded_inventory(self):
        for missing in ('sessionId','planId','playbackAttemptId','outputFingerprint','fileId','sourceId','itemId','scope'):
            proof = descriptor()
            del proof[missing]
            with self.subTest(missing=missing):
                self.assertIsNone(self.create(proof))
    def test_verified_playback_stall_is_bounded_and_pause_can_resume(self):
        state = self.event(self.create(),'inventory',inventory=inventory())['state']
        for position in (100,1100):
            state=self.event(state,'observation',nativeState='playing',positionMs=position,audioFormat='ac3',audioTrack='native-random-9')['state']
        paused = run_function([POLICY],'SiloUIOriginalReduce',[state,dict(kind='observation',token=7,generation=3,nowMs=60000,nativeState='paused')])['state']
        resumed = run_function([POLICY],'SiloUIOriginalReduce',[paused,dict(kind='tick',token=7,generation=3,nowMs=61000,nativeState='playing')])
        self.assertIsNone(resumed['command'])
        stalled = run_function([POLICY],'SiloUIOriginalReduce',[resumed['state'],dict(kind='tick',token=7,generation=3,nowMs=90000,nativeState='buffering')])
        self.assertEqual({'kind':'recover','reason':'stall_timeout'},stalled['command'])

    def test_output_change_and_handle_loss_retire_verified_selection(self):
        state=self.event(self.create(),'inventory',inventory=inventory())['state']
        for position in (100,1100):
            state=self.event(state,'observation',nativeState='playing',positionMs=position,audioFormat='ac3',audioTrack='native-random-9')['state']
        for patch in ({'outputFingerprint':'changed-output'},{'audioTrack':'stale-track'}):
            event=dict(kind='observation',token=7,generation=3,nowMs=2000,nativeState='playing',positionMs=2100,audioFormat='ac3',audioTrack='native-random-9')|patch
            result=run_function([POLICY],'SiloUIOriginalReduce',[state,event])
            self.assertEqual('recover',result['command']['kind'])
    def test_name_changes_do_not_replace_inventory_identity(self):
        state=self.event(self.create(),'inventory',inventory=inventory())['state']
        changed=inventory()
        changed[0]['Name']='Commentary AC3 TrueHD private title'
        result=self.event(state,'inventory',inventory=changed)
        self.assertIsNone(result['command'])
    def test_shipping_early_finish_dispatches_one_owned_recovery_and_restores_mute(self):
        self.shipping_finish_recovery(False)

    def test_shipping_verified_playing_premature_finish_recovers_once(self):
        self.shipping_finish_recovery(True)

    def shipping_finish_recovery(self, verified):
        import json
        import tempfile
        from tools.brightscript import run_brightscript
        from tests.test_silo_playback_policy import plan, SCOPE
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            player=root/'player.brs'
            player.write_text((ROOT/'components/SiloUIPlayer.brs').read_text().replace('sub PlayerClose(','sub UnusedPlayerClose(',1).replace('function PlayerOriginalOutputFingerprint()','function UnusedPlayerOriginalOutputFingerprint()',1))
            boundary=root/'boundary.brs'
            boundary.write_text('''function SiloUIOwner() as Object
 return m.owner
end function
function SiloUICleanupUuid() as String
 return "recover-request-0001"
end function
function PlayerOriginalOutputFingerprint() as String
 return "output-1"
end function
sub Api(action as String, params as Object, purpose as String, extra as Dynamic)
 m.sent.Push({action:action,params:params})
end sub
sub Toast(text as String)
end sub
sub PlayerClose(finished as Boolean)
 m.closed=finished
end sub
''')
            state=self.create()
            state['token']=4
            if verified: state['phase']='verified_playing'
            values=[state,plan(),SCOPE]
            encoded=json.dumps(values).replace('"','""')
            code='values=ParseJson("'+encoded+'")\n'+'''
 m.originalPlayback=values[0]:m.playPlan=values[1]:m.owner=values[2]
 m.originalGeneration=3:m.playToken=4:m.view="player":m.playLastPositionMs=12500:m.sent=[]:m.nativeSeenPlaying=true
 m.playVersions=[{sourceId:m.playPlan.sourceId,itemId:m.playPlan.itemId,versionId:m.playPlan.versionId,durationMs:7200000}]
 contentNode={identity:"current",isSameNode:function(other as Object) as Boolean
 return m.identity=other.identity
 end function}
 m.video={state:"finished",position:0,audioFormat:"",audioTrack:"",content:contentNode,mute:true,SetFields:function(fields as Object) as Boolean
 m.control=fields.control
 return true
 end function}
 m.originalContent=contentNode:m.originalTimer={control:"start"}:m.progressTimer={}
 m.originalClock={TotalMilliseconds:function() as Integer
 return 500
 end function}
 onVideoState()
 onVideoState()
 print FormatJson({sent:m.sent,muted:m.video.mute,guard:m.originalPlayback,closed:m.closed})
'''
            files=[POLICY,ROOT/'components/SiloUISubtitleArtifact.brs',player,boundary,ROOT/'source/core/SiloUIPlayerPolicy.brs',ROOT/'source/core/SiloUIFormat.brs',ROOT/'source/core/SiloPlaybackPolicy.brs',ROOT/'components/SiloUICompatPlayback.brs']
            result=json.loads(run_brightscript(files,code,root=root).strip().splitlines()[-1])
        self.assertEqual(1,len(result['sent']))
        self.assertEqual('playback_replan',result['sent'][0]['action'])
        self.assertEqual('decoder_failure',result['sent'][0]['params']['failureClassification'])
        self.assertFalse(result['muted'])
        self.assertIsNone(result['guard'])
        self.assertIsNone(result['closed'])

    def test_speculative_guarded_session_is_cleaned_up_without_binding(self):
        import json
        import tempfile
        from tools.brightscript import run_brightscript
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            player=root/'player.brs'
            player.write_text((ROOT/'components/SiloUIPlayer.brs').read_text().replace('sub PlayerStopSession(','sub UnusedPlayerStopSession(',1))
            boundary=root/'boundary.brs'
            boundary.write_text('''sub PlayerStopSession(plan as Object,persist as Boolean)
 m.cleaned=plan.sessionId
end sub
''')
            result=json.loads(run_brightscript([player,boundary,ROOT/'source/core/SiloUIFormat.brs'],'''
 m.prebuf={token:4}:m.video={content:"unchanged",control:"stop"}
 PlayerResult("play_prebuf",{ok:true,plan:{url:"private",sessionId:"owned-session",originalPlayback:{guarded:true}}},{},4)
 print FormatJson({cleaned:m.cleaned,prebuf:m.prebuf,content:m.video.content,control:m.video.control})
''',root=root).strip())
        self.assertEqual({'cleaned':'owned-session','prebuf':None,'content':'unchanged','control':'stop'},result)
    def test_malformed_event_or_numeric_native_facts_fail_closed(self):
        state=self.create()
        result=run_function([POLICY],'SiloUIOriginalReduce',[state,dict(kind='inventory',token=7,generation=3,nowMs='private',inventory=inventory())])
        self.assertIsNone(result['command'])
        self.assertEqual(state,result['state'])
        raw=inventory()
        raw[0]['Channels']='private'
        self.assertEqual('recover',self.event(state,'inventory',inventory=raw)['command']['kind'])
    def test_scene_observation_uses_actual_current_track_not_requested_track(self):
        import json
        import tempfile
        from tools.brightscript import run_brightscript
        state=self.event(self.create(),'inventory',inventory=inventory())['state']
        encoded=json.dumps(state).replace('"','""')
        with tempfile.TemporaryDirectory() as directory:
            code='m.originalPlayback=ParseJson("'+encoded+'")\n'+'''
 contentNode={identity:"current",isSameNode:function(other as Object) as Boolean
 return m.identity=other.identity
 end function}
 m.playToken=7:m.originalGeneration=3:m.originalContent=contentNode:m.originalFreshState=true:m.originalOutputFingerprint="output-1"
 m.video={content:contentNode,state:"playing",position:1,audioFormat:"ac3",audioTrack:"native-random-9",currentAudioTrack:"other-language-ac3",mute:true}
 m.originalClock={TotalMilliseconds:function() as Integer
 return 1000
 end function}
 PlayerOriginalObserve()
 m.video.position=2
 PlayerOriginalObserve()
 print FormatJson({phase:m.originalPlayback.phase,muted:m.video.mute})
'''
            result=json.loads(run_brightscript([POLICY,ROOT/'components/SiloUIPlayer.brs'],code,root=Path(directory)).strip())
        self.assertEqual({'phase':'selected','muted':True},result)

    def test_current_content_needs_fresh_buffering_before_inventory_can_select(self):
        import json
        import tempfile
        from tools.brightscript import run_brightscript
        state=self.create()
        values=json.dumps([state,inventory()]).replace('"','""')
        with tempfile.TemporaryDirectory() as directory:
            result=json.loads(run_brightscript([POLICY,ROOT/'components/SiloUIPlayer.brs'], 'values=ParseJson("'+values+'")\n'+'''
 m.originalPlayback=values[0]:m.playToken=7:m.originalGeneration=3
 contentNode={identity:"current",isSameNode:function(other as Object) as Boolean
 return m.identity=other.identity
 end function}
 m.originalContent=contentNode:m.originalDrained=true:m.originalFreshState=false
 m.video={content:contentNode,state:"playing",availableAudioTracks:values[1],audioTrack:"stale"}
 m.originalClock={TotalMilliseconds:function() as Integer
 return 1000
 end function}
 PlayerOriginalInventory()
 before=m.video.audioTrack
 m.video.state="buffering"
 PlayerOriginalInventory()
 print FormatJson({before:before,after:m.video.audioTrack})
''',root=Path(directory)).strip())
        self.assertEqual({'before':'stale','after':'native-random-9'},result)
    def test_paused_audio_change_waits_for_verified_start_before_restoring_pause(self):
        import json
        import tempfile
        from tools.brightscript import run_brightscript
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            player=root/'player.brs'
            player.write_text((ROOT/'components/SiloUIPlayer.brs').read_text().replace('sub PlayerOriginalObserve()','sub UnusedPlayerOriginalObserve()',1).replace('sub PlayerLoadMarkers()','sub UnusedPlayerLoadMarkers()',1))
            boundary=root/'boundary.brs'
            boundary.write_text('''sub PlayerOriginalObserve()
end sub
sub PlayerLoadMarkers()
end sub
''')
            result=json.loads(run_brightscript([player,ROOT/'components/SiloUISubtitleArtifact.brs',ROOT/'source/core/SiloUIFormat.brs',boundary,ROOT/'components/SiloUICompatPlayback.brs'],'''
 m.view="player":m.playPlan={startPositionMs:0}:m.audioRestorePause=true:m.video={state:"playing",control:"play",position:0}
 m.originalPlayback={phase:"selected"}
 onVideoState()
 pending={restore:m.audioRestorePause,control:m.video.control}
 m.originalPlayback.phase="verified_playing"
 onVideoState()
 print FormatJson({pending:pending,restore:m.audioRestorePause,control:m.video.control})
''',root=root).strip())
        self.assertEqual({'restore':True,'control':'play'},result['pending'])
        self.assertFalse(result['restore'])
        self.assertEqual('pause',result['control'])
    def test_source_audio_result_defers_guarded_pause_until_verification(self):
        import json
        import tempfile
        from tools.brightscript import run_brightscript
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            boundary=root/'boundary.brs'
            boundary.write_text('''sub PlayerStart(plan as Object)
 m.playPlan=plan
 m.originalPlayback={phase:"selected"}
end sub
''')
            player=root/'player.brs';player.write_text((ROOT/'components/SiloUIPlayer.brs').read_text().replace('sub PlayerStart(', 'sub UnusedPlayerStart(',1))
            result=json.loads(run_brightscript([ROOT/'components/SiloUIPlaybackChoices.brs',ROOT/'components/SiloUISubtitleArtifact.brs',player,ROOT/'source/core/SiloUIFormat.brs',boundary],'''
 m.view="player":m.playToken=4:m.playPlan={sessionId:"lease",planId:"old",versionId:"file",cleanupOwner:{generation:2}}
 m.progressSequence=9:m.playerReturn={}:m.savedCaptionMode="Off":m.trackPref={}:m.trackPrefLanes={}
 m.video={state:"playing",control:"play"}
 PlaybackAudioResult({ok:true,plan:{sessionId:"lease",planId:"new",versionId:"file"}},{token:4,sessionId:"lease",planId:"old",paused:true,language:"en",name:"English"})
 print FormatJson({pending:m.audioRestorePause,control:m.video.control})
''',root=root).strip())
        self.assertEqual({'pending':True,'control':'play'},result)

    def test_native_content_identity_gates_inventory_and_observations(self):
        import json
        import tempfile
        from tools.brightscript import run_brightscript
        values=json.dumps([descriptor(),inventory()]).replace('"','""')
        with tempfile.TemporaryDirectory() as directory:
            code='values=ParseJson("'+values+'")\n'+'''
 node={identity:"current",calls:0,isSameNode:function(other as Object) as Boolean
  m.calls++
  return m.identity=other.identity
 end function}
 m.originalPlayback=SiloUIOriginalCreate(values[0],7,3,0)
 m.playToken=7:m.originalGeneration=3:m.originalContent={identity:"current"}
 m.originalDrained=true:m.originalFreshState=true:m.originalOutputFingerprint="output-1"
 m.video={content:node,state:"buffering",availableAudioTracks:values[1],audioTrack:"old",position:0,currentAudioTrack:"native-random-9",audioFormat:"ac3",mute:true}
 m.originalClock={TotalMilliseconds:function() as Integer
  return 1000
 end function}
 PlayerOriginalInventory()
 selected=m.video.audioTrack
 m.video.state="playing":m.video.position=1
 PlayerOriginalObserve()
 m.video.position=2
 PlayerOriginalObserve()
 verified=m.originalPlayback.phase
 m.originalContent={identity:"retired"}
 m.video.availableAudioTracks=[{Track:"foreign",Format:"ac3",Language:"eng"}]
 m.originalPlayback.phase="selected":m.originalPlayback.playingPosition=invalid
 PlayerOriginalInventory()
 PlayerOriginalObserve()
 foreign={track:m.video.audioTrack,position:m.originalPlayback.playingPosition}
 m.video.content=invalid
 PlayerOriginalInventory()
 PlayerOriginalObserve()
 m.video.content=node:m.originalContent=invalid
 PlayerOriginalInventory()
 PlayerOriginalObserve()
 print FormatJson({selected:selected,verified:verified,foreign:foreign,identityCalls:node.calls})
'''
            result=json.loads(run_brightscript([POLICY,ROOT/'components/SiloUIPlayer.brs'],code,root=Path(directory)).strip())
        self.assertEqual('native-random-9',result['selected'])
        self.assertEqual('verified_playing',result['verified'])
        self.assertEqual({'track':'native-random-9','position':None},result['foreign'])
        self.assertEqual(5,result['identityCalls'])

    def test_early_finish_restarts_once_without_resetting_the_startup_deadline(self):
        import json
        import tempfile
        from tools.brightscript import run_brightscript
        payload=json.dumps([descriptor(),inventory()]).replace('"','""')
        with tempfile.TemporaryDirectory() as directory:
            code='values=ParseJson("'+payload+'")\n'+'''
 s=SiloUIOriginalCreate(values[0],7,3,0)
 s=SiloUIOriginalReduce(s,{kind:"observation",token:7,generation:3,nowMs:1000,nativeState:"buffering"}).state
 s=SiloUIOriginalReduce(s,{kind:"inventory",token:7,generation:3,nowMs:2000,inventory:values[1]}).state
 first=SiloUIOriginalReduce(s,{kind:"observation",token:7,generation:3,nowMs:5000,nativeState:"finished"})
 duplicate=SiloUIOriginalReduce(first.state,{kind:"observation",token:7,generation:4,nowMs:5001,nativeState:"finished"})
 expired=SiloUIOriginalReduce(duplicate.state,{kind:"tick",token:7,generation:4,nowMs:30000,nativeState:"buffering"})
 print FormatJson({first:{command:first.command,state:{phase:first.state.phase,generation:first.state.generation,startedMs:first.state.startedMs,trackId:first.state.trackId,playingPosition:first.state.playingPosition}},duplicate:duplicate.command,expired:expired.command})
'''
            result=json.loads(run_brightscript([POLICY],code,root=Path(directory)).strip())
        self.assertEqual({'kind':'restart'},result['first']['command'])
        state=result['first']['state']
        self.assertEqual('restarting',state['phase'])
        self.assertEqual(4,state['generation'])
        self.assertEqual(0,state['startedMs'])
        self.assertEqual('',state['trackId'])
        self.assertIsNone(state['playingPosition'])
        self.assertIsNone(result['duplicate'])
        self.assertEqual({'kind':'recover','reason':'startup_timeout'},result['expired'])

    def test_restart_needs_new_buffering_and_inventory_before_audio_can_verify(self):
        import json
        import tempfile
        from tools.brightscript import run_brightscript
        payload=json.dumps([descriptor(),inventory()]).replace('"','""')
        with tempfile.TemporaryDirectory() as directory:
            code='values=ParseJson("'+payload+'")\n'+'''
 s=SiloUIOriginalCreate(values[0],7,3,0)
 s=SiloUIOriginalReduce(s,{kind:"observation",token:7,generation:3,nowMs:1000,nativeState:"buffering"}).state
 s=SiloUIOriginalReduce(s,{kind:"observation",token:7,generation:3,nowMs:5000,nativeState:"finished"}).state
 old=SiloUIOriginalReduce(s,{kind:"inventory",token:7,generation:3,nowMs:5100,inventory:values[1],freshInventory:true})
 beforeBuffer=SiloUIOriginalReduce(s,{kind:"inventory",token:7,generation:4,nowMs:5200,inventory:values[1],freshInventory:true})
 s=SiloUIOriginalReduce(s,{kind:"observation",token:7,generation:4,nowMs:6000,nativeState:"buffering"}).state
 staleInventory=SiloUIOriginalReduce(s,{kind:"inventory",token:7,generation:4,nowMs:6100,inventory:values[1]})
 secondFailure=SiloUIOriginalReduce(s,{kind:"observation",token:7,generation:4,nowMs:6200,nativeState:"finished"})
 fresh=SiloUIOriginalReduce(s,{kind:"inventory",token:7,generation:4,nowMs:6300,inventory:values[1],freshInventory:true})
 s=SiloUIOriginalReduce(fresh.state,{kind:"observation",token:7,generation:4,nowMs:7000,nativeState:"playing",audioTrack:"native-random-9",audioFormat:"ac3",positionMs:1000}).state
 s=SiloUIOriginalReduce(s,{kind:"observation",token:7,generation:4,nowMs:8000,nativeState:"playing",audioTrack:"native-random-9",audioFormat:"ac3",positionMs:2000}).state
 print FormatJson({old:old.command,beforeBuffer:beforeBuffer.command,stale:staleInventory.command,secondFailure:secondFailure.command,fresh:fresh.command,phase:s.phase})
'''
            result=json.loads(run_brightscript([POLICY],code,root=Path(directory)).strip())
        self.assertIsNone(result['old'])
        self.assertIsNone(result['beforeBuffer'])
        self.assertIsNone(result['stale'])
        self.assertEqual({'kind':'recover','reason':'startup_failure'},result['secondFailure'])
        self.assertEqual({'kind':'select','trackId':'native-random-9'},result['fresh'])
        self.assertEqual('verified_playing',result['phase'])

    def test_scene_restart_reuses_content_lease_and_clock_without_completion(self):
        import json
        import tempfile
        from tools.brightscript import run_brightscript
        payload=json.dumps([descriptor(),inventory()]).replace('"','""')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            player=root/'player.brs'
            player.write_text((ROOT/'components/SiloUIPlayer.brs').read_text().replace('sub PlayerClose(','sub UnusedPlayerClose(',1))
            boundary=root/'boundary.brs'
            boundary.write_text('''sub PlayerClose(finished as Boolean)
 m.closed=finished
end sub
sub Api(action as String,params as Object,purpose as String,extra as Dynamic)
 m.sent.Push(action)
end sub
''')
            code='values=ParseJson("'+payload+'")\n'+'''
 contentNode={isSameNode:function(other as Object) as Boolean
 return true
 end function}
 m.originalPlayback=SiloUIOriginalCreate(values[0],7,3,0)
 m.originalPlayback=SiloUIOriginalReduce(m.originalPlayback,{kind:"observation",token:7,generation:3,nowMs:1000,nativeState:"buffering"}).state
 m.originalPlayback=SiloUIOriginalReduce(m.originalPlayback,{kind:"inventory",token:7,generation:3,nowMs:2000,inventory:values[1]}).state
 m.view="player":m.playToken=7:m.originalGeneration=3:m.originalContent=contentNode
 m.originalFreshState=true:m.originalDrained=true:m.originalOutputFingerprint="output-1"
 m.playPlan={sessionId:"same-lease"}:m.playLastPositionMs=125000:m.sent=[]
 m.video={state:"finished",content:contentNode,availableAudioTracks:values[1],position:0,mute:true,controls:[],SetFields:function(fields as Object) as Boolean
 m.controls.Push(fields.control)
 m.control=fields.control
 return true
 end function}
 m.originalClock={nowMs:5000,TotalMilliseconds:function() as Integer
 return m.nowMs
 end function}
 onVideoState()
 onVideoState()
 print FormatJson({controls:m.video.controls,phase:m.originalPlayback.phase,generation:m.originalGeneration,nowMs:m.originalClock.TotalMilliseconds(),session:m.playPlan.sessionId,token:m.playToken,position:m.playLastPositionMs,muted:m.video.mute,sent:m.sent,closed:m.closed,fresh:m.originalFreshState,drained:m.originalDrained})
'''
            result=json.loads(run_brightscript([POLICY,ROOT/'components/SiloUISubtitleArtifact.brs',player,boundary,ROOT/'components/SiloUICompatPlayback.brs'],code,root=root).strip())
        self.assertEqual(['stop','play'],result['controls'])
        self.assertEqual('restarting',result['phase'])
        self.assertEqual(4,result['generation'])
        self.assertEqual(5000,result['nowMs'])
        self.assertEqual('same-lease',result['session'])
        self.assertEqual(7,result['token'])
        self.assertEqual(125000,result['position'])
        self.assertTrue(result['muted'])
        self.assertFalse(result['fresh'])
        self.assertFalse(result['drained'])
        self.assertEqual([],result['sent'])
        self.assertIsNone(result['closed'])

    def test_restart_accepts_same_inventory_only_after_fresh_audio_callback(self):
        import json
        import tempfile
        from tools.brightscript import run_brightscript
        payload=json.dumps([descriptor(),inventory()]).replace('"','""')
        with tempfile.TemporaryDirectory() as directory:
            code='values=ParseJson("'+payload+'")\n'+'''
 contentNode={isSameNode:function(other as Object) as Boolean
 return true
 end function}
 s=SiloUIOriginalCreate(values[0],7,3,0)
 s=SiloUIOriginalReduce(s,{kind:"observation",token:7,generation:3,nowMs:1000,nativeState:"buffering"}).state
 m.originalPlayback=SiloUIOriginalReduce(s,{kind:"observation",token:7,generation:3,nowMs:5000,nativeState:"finished"}).state
 m.playToken=7:m.originalGeneration=4:m.originalContent=contentNode:m.originalFreshState=false:m.originalDrained=false
 m.originalOldInventory=SiloUIOriginalInventorySignature(values[1]):m.originalOutputFingerprint="output-1"
 m.view="player":m.playPlan={}:m.trackPref={subtitle:"off"}:m.trackPrefLanes={}
 m.video={content:contentNode,state:"buffering",availableAudioTracks:values[1],availableSubtitleTracks:[],audioTrack:"stale",position:0}
 m.originalClock={TotalMilliseconds:function() as Integer
 return 6000
 end function}
 onPlayerTracks({GetField:function() as String
 return "availableSubtitleTracks"
 end function})
 stale=m.video.audioTrack
 onPlayerTracks({GetField:function() as String
 return "availableAudioTracks"
 end function})
 print FormatJson({stale:stale,fresh:m.video.audioTrack,phase:m.originalPlayback.phase})
'''
            files=[POLICY,ROOT/'components/SiloUISubtitleArtifact.brs',ROOT/'components/SiloUIPlayer.brs',ROOT/'source/core/TrackPreference.brs']
            result=json.loads(run_brightscript(files,code,root=Path(directory)).strip())
        self.assertEqual({'stale':'stale','fresh':'native-random-9','phase':'selected'},result)

    def test_guarded_close_reports_snapshot_before_native_stop_resets_position(self):
        import json
        import tempfile
        from tools.brightscript import run_brightscript
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            player=root/'player.brs'
            player.write_text((ROOT/'components/SiloUIPlayer.brs').read_text().replace('sub PlayerResetChrome()','sub UnusedPlayerResetChrome()',1))
            boundary=root/'boundary.brs'
            boundary.write_text('''sub PlayerResetChrome()
end sub
sub Api(action as String,params as Object,purpose as String,extra as Dynamic)
 m.sent.Push({action:action,position:params.positionMs})
end sub
sub HomeUpdateProgress(item as Object,scope as Dynamic)
end sub
sub ShowView(view as String)
 m.view=view
end sub
sub SetZone(zone as String)
end sub
''')
            code='''results=[]
 for each phase in ["restarting","verified_playing"]
 m.view="player":m.provider="silo":m.playToken=7:m.progressSequence=0:m.sent=[]
 m.playPlan={sessionId:"same-lease",installationId:"install",timelineOffsetMs:0}
 m.playItem={resumeMs:125000,watched:false}:m.playLastPositionMs=125000
 m.originalPlayback={phase:phase}:m.originalTimer={control:"start"}:m.progressTimer={control:"start"}
 nativePosition=0
 if phase="verified_playing" then nativePosition=125
 m.video={position:nativePosition,state:"playing",mute:true,stops:0,SetFields:function(fields as Object) as Boolean
 m.stops++:m.position=0:m.state="stopped":m.control=fields.control
 return true
 end function}
 m.playerReturn={view:"detail",zone:"detailButtons"}
 PlayerClose(false,false)
 results.Push({phase:phase,reports:m.sent,resume:m.playItem.resumeMs,watched:m.playItem.watched,nativePosition:m.video.position,stops:m.video.stops,guard:m.originalPlayback,muted:m.video.mute,timer:m.originalTimer.control})
 end for
 print FormatJson(results)
'''
            result=json.loads(run_brightscript([POLICY,ROOT/'components/SiloUISubtitleArtifact.brs',ROOT/'components/SiloUIRobustness.brs',player,boundary,ROOT/'source/core/SiloUIFormat.brs'],code,root=root).strip())
        for value in result:
            with self.subTest(phase=value['phase']):
                self.assertEqual([{'action':'playback_stop','position':125000}],value['reports'])
                self.assertEqual(125000,value['resume'])
                self.assertFalse(value['watched'])
                self.assertEqual(0,value['nativePosition'])
                self.assertEqual(1,value['stops'])
                self.assertIsNone(value['guard'])
                self.assertFalse(value['muted'])
                self.assertEqual('stop',value['timer'])

    def test_cancelled_restart_cannot_select_or_recover_and_output_change_never_restarts(self):
        import json
        import tempfile
        from tools.brightscript import run_brightscript
        payload=json.dumps([descriptor(),inventory()]).replace('"','""')
        with tempfile.TemporaryDirectory() as directory:
            code='values=ParseJson("'+payload+'")\n'+'''
 s=SiloUIOriginalCreate(values[0],7,3,0)
 s=SiloUIOriginalReduce(s,{kind:"observation",token:7,generation:3,nowMs:1000,nativeState:"buffering"}).state
 changed=SiloUIOriginalReduce(s,{kind:"observation",token:7,generation:3,nowMs:5000,nativeState:"finished",outputFingerprint:"changed"})
 nativeError=SiloUIOriginalReduce(s,{kind:"observation",token:7,generation:3,nowMs:5000,nativeState:"error"})
 restarted=SiloUIOriginalReduce(s,{kind:"observation",token:7,generation:3,nowMs:5000,nativeState:"finished"}).state
 closed=SiloUIOriginalReduce(restarted,{kind:"cancel",token:7,generation:4,nowMs:6000}).state
 lateInventory=SiloUIOriginalReduce(closed,{kind:"inventory",token:7,generation:4,nowMs:7000,inventory:values[1],freshInventory:true})
 lateTimeout=SiloUIOriginalReduce(closed,{kind:"tick",token:7,generation:4,nowMs:31000})
 print FormatJson({changed:changed.command,nativeError:nativeError.command,phase:closed.phase,lateInventory:lateInventory.command,lateTimeout:lateTimeout.command})
'''
            result=json.loads(run_brightscript([POLICY],code,root=Path(directory)).strip())
        self.assertEqual({'kind':'recover','reason':'output_changed'},result['changed'])
        self.assertEqual({'kind':'recover','reason':'native_error'},result['nativeError'])
        self.assertEqual('closed',result['phase'])
        self.assertIsNone(result['lateInventory'])
        self.assertIsNone(result['lateTimeout'])

    def test_same_content_restart_rereads_unchanged_inventory_after_new_buffering(self):
        import json
        import tempfile
        from tools.brightscript import run_brightscript
        payload=json.dumps([descriptor(),inventory()]).replace('"','""')
        with tempfile.TemporaryDirectory() as directory:
            code='values=ParseJson("'+payload+'")\n'+'''
 s=SiloUIOriginalCreate(values[0],7,3,0)
 initial=SiloUIOriginalReduce(s,{kind:"inventory",token:7,generation:3,nowMs:500,inventory:values[1],provenance:"same_content_restart",bindingValidated:true})
 s=SiloUIOriginalReduce(s,{kind:"observation",token:7,generation:3,nowMs:1000,nativeState:"buffering"}).state
 s=SiloUIOriginalReduce(s,{kind:"inventory",token:7,generation:3,nowMs:2000,inventory:values[1]}).state
 s=SiloUIOriginalReduce(s,{kind:"observation",token:7,generation:3,nowMs:5000,nativeState:"finished"}).state
 before=SiloUIOriginalReduce(s,{kind:"inventory",token:7,generation:4,nowMs:5100,inventory:values[1],provenance:"same_content_restart",bindingValidated:true})
 s=SiloUIOriginalReduce(s,{kind:"observation",token:7,generation:4,nowMs:6000,nativeState:"buffering"}).state
 after=SiloUIOriginalReduce(s,{kind:"inventory",token:7,generation:4,nowMs:6100,inventory:values[1],provenance:"same_content_restart",bindingValidated:true})
 print FormatJson({initial:initial.command,before:before.command,after:after.command,provenance:after.state.mappingProvenance})
'''
            result=json.loads(run_brightscript([POLICY],code,root=Path(directory)).strip())
        self.assertIsNone(result['initial'])
        self.assertIsNone(result['before'])
        self.assertEqual({'kind':'select','trackId':'native-random-9'},result['after'])
        self.assertEqual('same_content_restart',result['provenance'])

    def test_same_content_restart_requires_initial_mapping_and_exact_subset(self):
        import json
        import tempfile
        from tools.brightscript import run_brightscript
        other=descriptor()
        other['sourceAudio'][0]['codec']='aac'
        changed=inventory()
        changed[0]['Track']='new-current-handle'
        payload=json.dumps([descriptor(),inventory(),other,inventory()+[dict(Track='extra',Format='aac',Language='eng')],changed]).replace('"','""')
        with tempfile.TemporaryDirectory() as directory:
            code='values=ParseJson("'+payload+'")\n'+'''
 results=[]
 for each variant in ["missing_initial","other_source","other_native","changed_handle"]
 proof=values[0]
 if variant="other_source" then proof=values[2]
 s=SiloUIOriginalCreate(proof,7,3,0)
 s=SiloUIOriginalReduce(s,{kind:"observation",token:7,generation:3,nowMs:1000,nativeState:"buffering"}).state
 if variant<>"missing_initial" then s=SiloUIOriginalReduce(s,{kind:"inventory",token:7,generation:3,nowMs:2000,inventory:values[1]}).state
 s=SiloUIOriginalReduce(s,{kind:"observation",token:7,generation:3,nowMs:5000,nativeState:"finished"}).state
 s=SiloUIOriginalReduce(s,{kind:"observation",token:7,generation:4,nowMs:6000,nativeState:"buffering"}).state
 raw=values[1]
 if variant="other_native" then raw=values[3]
 if variant="changed_handle" then raw=values[4]
 resolved=SiloUIOriginalReduce(s,{kind:"inventory",token:7,generation:4,nowMs:6100,inventory:raw,provenance:"same_content_restart",bindingValidated:true})
 results.Push({variant:variant,command:resolved.command})
 end for
 print FormatJson(results)
'''
            result=json.loads(run_brightscript([POLICY],code,root=Path(directory)).strip())
        for value in result:
            if value['variant']=='changed_handle':
                self.assertEqual({'kind':'select','trackId':'new-current-handle'},value['command'])
            else:
                self.assertEqual({'kind':'recover','reason':'audio_unverified'},value['command'])

    def test_same_content_binding_rejects_replacement_mutation_owner_and_output_changes(self):
        import json
        import tempfile
        from tools.brightscript import run_brightscript
        payload=json.dumps(descriptor()).replace('"','""')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            player=root/'player.brs'
            player.write_text((ROOT/'components/SiloUIPlayer.brs').read_text().replace('function PlayerOriginalOutputFingerprint()','function UnusedPlayerOriginalOutputFingerprint()',1))
            boundary=root/'boundary.brs'
            boundary.write_text('''function PlayerOriginalOutputFingerprint() as String
 return m.outputFingerprint
end function
''')
            code='proof=ParseJson("'+payload+'")\n'+'''
 results=[]
 for each variant in ["current","new_video","new_content","url","plan_url","format","source","file","lease","plan","attempt","owner","output"]
 m.provider="silo":m.sourceId=proof.sourceId:m.profileId="profile-1":m.generation=9:m.playToken=7:m.outputFingerprint="output-1"
 contentNode={identity:"original",url:"https://example.invalid/owned",streamFormat:"mkv",isSameNode:function(other as Object) as Boolean
 return m.identity=other.identity
 end function}
 m.video={identity:"video",content:contentNode,isSameNode:function(other as Object) as Boolean
 return m.identity=other.identity
 end function}
 m.originalContent=contentNode
 m.playPlan={provider:"silo",sourceId:proof.sourceId,itemId:proof.itemId,versionId:proof.fileId,sessionId:proof.sessionId,planId:proof.planId,url:contentNode.url,streamFormat:"mkv",originalPlayback:proof,siloPlayback:{playbackAttemptId:proof.playbackAttemptId}}
 m.originalPlayback=SiloUIOriginalCreate(proof,7,3,0)
 m.originalBinding=PlayerOriginalCaptureBinding()
 if variant="new_video"
 m.video={identity:"replacement",content:contentNode,isSameNode:function(other as Object) as Boolean
 return m.identity=other.identity
 end function}
 end if
 if variant="new_content"
 m.video.content={identity:"replacement",isSameNode:function(other as Object) as Boolean
 return m.identity=other.identity
 end function}
 end if
 if variant="url" then contentNode.url="https://example.invalid/replacement"
 if variant="plan_url" then m.playPlan.url="https://example.invalid/plan-replaced"
 if variant="format" then contentNode.streamFormat="mp4"
 if variant="source" then m.playPlan.sourceId="foreign-source"
 if variant="file" then m.playPlan.versionId="foreign-file"
 if variant="lease" then m.playPlan.sessionId="foreign-lease"
 if variant="plan" then m.playPlan.planId="foreign-plan"
 if variant="attempt" then m.playPlan.siloPlayback.playbackAttemptId="foreign-attempt"
 if variant="owner" then m.profileId="foreign-profile"
 if variant="output" then m.outputFingerprint="changed-output"
 results.Push({variant:variant,valid:PlayerOriginalBindingValid()})
 end for
 print FormatJson(results)
'''
            files=[POLICY,ROOT/'components/SiloUISubtitleArtifact.brs',player,boundary,ROOT/'source/core/SiloUIFormat.brs',ROOT/'components/SiloUIRobustness.brs']
            result=json.loads(run_brightscript(files,code,root=root).strip())
        for value in result:
            self.assertEqual(value['variant']=='current',value['valid'],value['variant'])

    def test_scene_same_content_restart_resolves_live_inventory_and_actual_readback(self):
        import json
        import tempfile
        from tools.brightscript import run_brightscript
        payload=json.dumps([descriptor(),inventory()]).replace('"','""')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            player=root/'player.brs'
            player.write_text((ROOT/'components/SiloUIPlayer.brs').read_text().replace('function PlayerOriginalOutputFingerprint()','function UnusedPlayerOriginalOutputFingerprint()',1))
            boundary=root/'boundary.brs'
            boundary.write_text('''function PlayerOriginalOutputFingerprint() as String
 return "output-1"
end function
''')
            code='values=ParseJson("'+payload+'")\n'+'''
 proof=values[0]
 m.provider="silo":m.sourceId=proof.sourceId:m.profileId="profile-1":m.generation=9:m.playToken=7:m.originalGeneration=3
 contentNode={identity:"content",url:"https://example.invalid/owned",streamFormat:"mkv",isSameNode:function(other as Object) as Boolean
 return m.identity=other.identity
 end function}
 m.originalContent=contentNode:m.originalFreshState=true:m.originalDrained=true:m.originalOldInventory="":m.originalOutputFingerprint="output-1"
 m.video={identity:"video",content:contentNode,state:"buffering",availableAudioTracks:values[1],audioTrack:"",currentAudioTrack:"native-random-9",audioFormat:"ac3",position:0,mute:true,isSameNode:function(other as Object) as Boolean
 return m.identity=other.identity
 end function,SetFields:function(fields as Object) as Boolean
 m.control=fields.control
 return true
 end function}
 m.playPlan={provider:"silo",sourceId:proof.sourceId,itemId:proof.itemId,versionId:proof.fileId,sessionId:proof.sessionId,planId:proof.planId,url:contentNode.url,streamFormat:"mkv",originalPlayback:proof,siloPlayback:{playbackAttemptId:proof.playbackAttemptId}}
 m.originalPlayback=SiloUIOriginalCreate(proof,7,3,0)
 m.originalBinding=PlayerOriginalCaptureBinding()
 m.originalClock={nowMs:1000,TotalMilliseconds:function() as Integer
 return m.nowMs
 end function}
 PlayerOriginalObserve()
 PlayerOriginalInventory(true)
 m.video.state="finished":m.originalClock.nowMs=5000
 PlayerOriginalObserve()
 m.video.state="buffering":m.originalClock.nowMs=6000
 PlayerOriginalInventory()
 selected=m.originalPlayback.phase
 m.video.state="playing":m.video.position=1:m.originalClock.nowMs=7000
 PlayerOriginalObserve()
 m.video.position=2:m.originalClock.nowMs=8000
 PlayerOriginalObserve()
 print FormatJson({selected:selected,phase:m.originalPlayback.phase,provenance:m.originalPlayback.mappingProvenance,track:m.video.audioTrack,muted:m.video.mute,startedMs:m.originalPlayback.startedMs})
'''
            files=[POLICY,ROOT/'components/SiloUISubtitleArtifact.brs',player,boundary,ROOT/'source/core/SiloUIFormat.brs',ROOT/'components/SiloUIRobustness.brs']
            result=json.loads(run_brightscript(files,code,root=root).strip())
        self.assertEqual({'selected':'selected','phase':'verified_playing','provenance':'same_content_restart','track':'native-random-9','muted':False,'startedMs':0},result)

    def test_same_content_verification_rechecks_owner_and_changed_inventory(self):
        import json
        import tempfile
        from tools.brightscript import run_brightscript
        changed=inventory()
        changed[0]['Track']='replacement-current'
        payload=json.dumps([descriptor(),inventory(),changed]).replace('"','""')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            player=root/'player.brs'
            player.write_text((ROOT/'components/SiloUIPlayer.brs').read_text().replace('function PlayerOriginalOutputFingerprint()','function UnusedPlayerOriginalOutputFingerprint()',1).replace('function PlayerRecoverNativeFailure(','function UnusedPlayerRecoverNativeFailure(',1))
            boundary=root/'boundary.brs'
            boundary.write_text('''function PlayerOriginalOutputFingerprint() as String
 return "output-1"
end function
function PlayerRecoverNativeFailure(reason as String) as Boolean
 m.recovered=reason
 PlayerOriginalClear()
 return true
end function
''')
            code='values=ParseJson("'+payload+'")\n'+'''
 results=[]
 for each variant in ["owner","inventory"]
 proof=values[0]:m.recovered=invalid
 m.provider="silo":m.sourceId=proof.sourceId:m.profileId="profile-1":m.generation=9:m.playToken=7:m.originalGeneration=4
 contentNode={identity:"content",url:"https://example.invalid/owned",streamFormat:"mkv",isSameNode:function(other as Object) as Boolean
 return m.identity=other.identity
 end function}
 m.originalContent=contentNode:m.originalFreshState=true:m.originalDrained=false:m.originalOutputFingerprint="output-1"
 m.video={identity:"video",content:contentNode,state:"playing",availableAudioTracks:values[1],audioTrack:"native-random-9",currentAudioTrack:"native-random-9",audioFormat:"ac3",position:1,mute:true,isSameNode:function(other as Object) as Boolean
 return m.identity=other.identity
 end function,SetFields:function(fields as Object) as Boolean
 m.control=fields.control
 return true
 end function}
 m.playPlan={provider:"silo",sourceId:proof.sourceId,itemId:proof.itemId,versionId:proof.fileId,sessionId:proof.sessionId,planId:proof.planId,url:contentNode.url,streamFormat:"mkv",originalPlayback:proof,siloPlayback:{playbackAttemptId:proof.playbackAttemptId}}
 s=SiloUIOriginalCreate(proof,7,3,0)
 s=SiloUIOriginalReduce(s,{kind:"observation",token:7,generation:3,nowMs:1000,nativeState:"buffering"}).state
 s=SiloUIOriginalReduce(s,{kind:"inventory",token:7,generation:3,nowMs:2000,inventory:values[1]}).state
 s=SiloUIOriginalReduce(s,{kind:"observation",token:7,generation:3,nowMs:5000,nativeState:"finished"}).state
 s=SiloUIOriginalReduce(s,{kind:"observation",token:7,generation:4,nowMs:6000,nativeState:"buffering"}).state
 m.originalPlayback=SiloUIOriginalReduce(s,{kind:"inventory",token:7,generation:4,nowMs:6100,inventory:values[1],provenance:"same_content_restart",bindingValidated:true}).state
 m.originalBinding=PlayerOriginalCaptureBinding()
 m.originalClock={TotalMilliseconds:function() as Integer
 return 7000
 end function}
 PlayerOriginalObserve()
 if variant="owner" then m.profileId="foreign"
 if variant="inventory" then m.video.availableAudioTracks=values[2]
 m.video.position=2
 PlayerOriginalObserve()
 phase="closed"
 if m.originalPlayback<>invalid then phase=m.originalPlayback.phase
 results.Push({variant:variant,phase:phase,recovered:m.recovered,track:m.video.audioTrack,muted:m.video.mute})
 end for
 print FormatJson(results)
'''
            files=[POLICY,ROOT/'components/SiloUISubtitleArtifact.brs',player,boundary,ROOT/'source/core/SiloUIFormat.brs',ROOT/'components/SiloUIRobustness.brs']
            result=json.loads(run_brightscript(files,code,root=root).strip())
        self.assertEqual('closed',result[0]['phase'])
        self.assertEqual('decoder_failure',result[0]['recovered'])
        self.assertEqual('selected',result[1]['phase'])
        self.assertEqual('replacement-current',result[1]['track'])
        self.assertTrue(result[1]['muted'])
