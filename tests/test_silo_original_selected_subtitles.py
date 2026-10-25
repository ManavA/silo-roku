"""Ordinary Original retains text selection under the existing artifact owner."""
import tempfile
import unittest
from pathlib import Path
from tools.brightscript import run_function
from tests import test_silo_ordinary_p8_original as ordinary
from tests.test_silo_selected_subtitle_receipt import selected

VTT='WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nSelected caption\n'

class OriginalSelectedSubtitles(unittest.TestCase):
    def start(self, change=None, options=None, scenario=None, features=None):
        def caption(wire, decision):
            raw=decision['playback_plan']
            chosen=selected(file_id='731',session=decision['session_id'])
            chosen['selected_tracks']['audio']=raw['selected_tracks']['audio']
            raw.update(chosen)
            wire['versions'][0]['subtitle_tracks']=[dict(index=7,codec='subrip',language='en',default=True,forced=False,hearing_impaired=False,external=False),dict(index=8,codec='subrip',language='fr',default=False,forced=False,hearing_impaired=False,external=True)]
            raw['subtitle']['inventory'][1].update(source='embedded',default=True)
            if change:change(wire,decision)
        opts=dict(subtitleMode='on',subtitleTrackId='file:731:subtitle:1',subtitleTrackIndex=1)
        opts.update(options or {})
        return ordinary.OrdinaryP8Original().start(mutate=caption,options=opts,features=features,subtitle_scenario=scenario or {'body':VTT,'headers':{'Content-Type':'text/vtt'},'stockSubtitleSelection':True})

    def test_selected_vtt_preserves_original_claims_and_file_owned_ready_caption(self):
        result=self.start()
        self.assertTrue(result['outcome']['ok'],result['outcome'])
        body=ordinary.OrdinaryP8Original().body(result)
        self.assertEqual('file:731:subtitle:1',body['subtitle_track_id'])
        self.assertEqual(1,body['subtitle_track_index'])
        self.assertIn('client_managed_dynamic_range_v1',body['client_playback_context']['deliveries']['original_http']['validated_claims'])
        plan=result['outcome']['plan']
        self.assertIn('originalPlayback',plan)
        self.assertEqual('sidecar_ready',plan['selectedSubtitle']['kind'])
        owner=plan['subtitleArtifact']['owner']
        self.assertEqual(('731',plan['sessionId'],plan['planAttemptKey'],7,41),tuple(owner[k] for k in ('fileId','sessionId','planAttemptKey','generation','requestId')))
        self.assertEqual(1,len(result['downloads']))
        self.assertEqual(plan['subtitleArtifact']['uri'],result['binding']['uri'])

    def test_always_without_explicit_selector_uses_server_selected_owned_text(self):
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            boundary=Path(directory)/'foreground.brs'
            boundary.write_text('''
sub Api(action as String,params as Object,purpose as String,extra as Dynamic)
 m.sent={action:action,params:params,purpose:purpose}
end sub
function ForegroundAlways() as Object
 m.playClock={TotalMilliseconds:function() as Integer
  return 0
 end function}
 m.playToken=7:m.playSelectedVersion="731":m.playStartMs=0:m.provider="silo":m.preferences={subtitles:"always"}
 m.playItem={itemId:"fixture-item"}
 data={item:{itemId:"fixture-item"},versions:[{versionId:"731"}],markers:[]}
 PlayerResult("play_detail",{ok:true},data,7)
 return {sent:m.sent,preference:m.preferences.subtitles}
end function
''')
            files=[root/'components/SiloUIPlayer.brs',root/'source/core/SiloUISettingsPolicy.brs',root/'source/core/SiloUIDetailPolicy.brs',root/'source/core/SiloUIFormat.brs',boundary]
            foreground=run_function(files,'ForegroundAlways',[],root=Path(directory))
        self.assertEqual('always',foreground['preference'])
        self.assertEqual('always',foreground['sent']['params']['subtitlemode'])
        self.assertEqual('playback_start',foreground['sent']['action'])
        result=self.start(options={'subtitleMode':foreground['sent']['params']['subtitlemode'],'subtitlePreferences':foreground['sent']['params']['subtitlepreferences'],'subtitleTrackId':None,'subtitleTrackIndex':None})
        self.assertTrue(result['outcome']['ok'],result['outcome'])
        self.assertEqual('sidecar_ready',result['outcome']['plan']['selectedSubtitle']['kind'])
        body=ordinary.OrdinaryP8Original().body(result)
        self.assertEqual(('file:731:subtitle:1',1),(body['subtitle_track_id'],body['subtitle_track_index']))
        self.assertNotIn('subtitleTrackId',result['submittedParams'])
        self.assertNotIn('subtitleTrackIndex',result['submittedParams'])

    def test_header_owned_embedded_text_sidecar_binds_without_foreground_download(self):
        def converted(wire,decision):
            raw=decision['playback_plan']
            raw['subtitle']['inventory'][1].update(source='embedded')
            raw['stream']['url']='/api/v2/stream/'+decision['session_id']
        result=self.start(converted,{'mediaAuthMode':'api_header_v1','subtitleMode':'always'},features=['header_authenticated_media_v1'])
        self.assertTrue(result['outcome']['ok'],result['outcome'])
        plan=result['outcome']['plan']
        self.assertIn('originalPlayback',plan)
        self.assertEqual('sidecar_pending',plan['selectedSubtitle']['kind'])
        self.assertEqual(plan['subtitleTransport']['uri'],result['binding']['uri'])
        self.assertEqual([],result['downloads'])
        self.assertEqual({},result['files'])

    def test_mismatched_selection_and_unowned_artifacts_refuse_before_download(self):
        def wrong_file(wire,decision):
            decision['playback_plan']['subtitle']['artifact']['url']=decision['playback_plan']['subtitle']['artifact']['url'].replace('file_id=731','file_id=732')
        def embedded(wire,decision):
            sub=decision['playback_plan']['subtitle'];sub.pop('artifact')
            sub['inventory'][1]['source']='embedded';sub['embedded']={'stream_index':3}
        def wrong_session(wire,decision):
            sub=decision['playback_plan']['subtitle']
            sub['artifact']['url']=sub['artifact']['url'].replace(decision['session_id'],'other-session')
            sub['inventory'][1]['url']=sub['artifact']['url']
        def bitmap(wire,decision):
            decision['playback_plan']['subtitle']['inventory'][1]['codec']='pgs'
        def wrong_attempt(wire,decision):
            decision['playback_plan']['plan_attempt_key']=''
        def deselected(wire,decision):
            raw=decision['playback_plan']
            raw['subtitle'].update(mode='off',track_id='')
            raw['subtitle'].pop('artifact')
            raw['selected_tracks'].pop('subtitle')
        def wrong_clock(wire,decision):
            decision['playback_plan']['subtitle']['artifact']['timing_origin_seconds']=10
        for change,opts,reason in ((wrong_file,{},'receipt_subtitle_invalid'),(wrong_session,{},'receipt_subtitle_invalid'),(wrong_attempt,{},'receipt_session'),(deselected,{},'receipt_subtitle_delivery'),(wrong_clock,{},'receipt_subtitle_clock'),(bitmap,{},'receipt_subtitle_codec'),(embedded,{},'receipt_subtitle_delivery'),(None,{'subtitleTrackIndex':0,'subtitleTrackId':'file:731:subtitle:0'},'receipt_subtitle_selection')):
            with self.subTest(change=change,options=opts):
                result=self.start(change,opts)
                self.assertFalse(result['outcome']['ok'],result['outcome'].get('errorCode'))
                self.assertEqual([],result['downloads'])
                self.assertEqual(reason,result['outcome']['startAttempts'][-1].get('validationReason'))

    def test_experimental_original_still_refuses_caption_preferences_before_allocation(self):
        from tests.test_silo_experimental_play import ExperimentalPlayTests
        experiment=ExperimentalPlayTests()
        experiment.setUp()
        for mode in ('on','always'):
            with self.subTest(mode=mode):
                result=experiment.start({'subtitleMode':mode})
                self.assertFalse(result['outcome']['ok'])
                self.assertFalse(any(request['method']=='POST' for request in result['requests']))

    def test_refused_original_caption_keeps_safe_validation_facts_and_owned_cleanup(self):
        def wrong_clock(wire,decision):
            decision['playback_plan']['subtitle']['artifact']['timing_origin_seconds']=10
        result=self.start(wrong_clock,{'subtitleMode':'always'})
        failure=result['outcome']
        self.assertFalse(failure['ok'])
        self.assertEqual('invalid_original_receipt',failure['errorCode'])
        attempt=failure['startAttempts'][-1]
        self.assertEqual('original_receipt',attempt.get('validationStage'))
        self.assertEqual('receipt_subtitle_clock',attempt.get('validationReason'))
        self.assertIn('startRequestFacts',failure)
        self.assertIn('startResponseFacts',failure)
        self.assertEqual(1,sum(request['method']=='DELETE' for request in result['requests']))
        self.assertEqual([],result['downloads'])
        self.assertNotIn('plan',failure)
        root=Path(__file__).resolve().parents[1]
        files=[root/'components/SiloUIPlayer.brs',root/'source/core/SiloPlaybackPolicy.brs',root/'source/adapters/SiloAdapter.brs']
        message=run_function(files,'PlayerStartAttemptsMessage',[failure['startAttempts']])
        self.assertIn('Validation: original_receipt / receipt_subtitle_clock',message)
        poisoned=dict(attempt,validationReason='https://private.example/token')
        safe=run_function([root/'source/core/SiloPlaybackPolicy.brs',root/'source/adapters/SiloAdapter.brs'],'SiloStartAttempts',[[poisoned]])
        self.assertNotIn('private.example',str(safe))

    def default_choice(self, tracks, file_id='731', preferences=None):
        root=Path(__file__).resolve().parents[1]
        return run_function([root/'source/core/SiloOriginalPlaybackPolicy.brs',root/'source/core/SiloPlaybackPolicy.brs',root/'source/adapters/SiloAdapter.brs'],'SiloOriginalDefaultSubtitle',[dict(file_id=file_id,subtitle_tracks=tracks),preferences])

    def test_fresh_default_uses_external_first_ordinal_and_recomputes_for_another_file(self):
        embedded=dict(index=17,codec='subrip',language='en',default=True,forced=True,hearing_impaired=False,external=False)
        external=dict(embedded,index=20,default=False,forced=False,external=True)
        self.assertEqual('file:731:subtitle:1',self.default_choice([embedded,external])['trackId'])
        self.assertEqual('file:732:subtitle:2',self.default_choice([embedded,external,dict(external,index=21)],'732')['trackId'])
        self.assertEqual('file:733:subtitle:0',self.default_choice([dict(embedded,default=False),dict(external,default=True)],'733')['trackId'])
        self.assertTrue(embedded['default'])
        self.assertEqual('file:734:subtitle:0',self.default_choice([embedded]+[dict(embedded,index=18+i,default=False,forced=False) for i in range(4)],'734')['trackId'])

    def test_fresh_default_refuses_ambiguity_missing_metadata_and_preference_mismatch(self):
        track=dict(index=7,codec='subrip',language='en',default=True,forced=True,hearing_impaired=False,external=False)
        for tracks,prefs in (([dict(track,default=False)],None),([track,dict(track,index=8)],None),([dict(track,codec=[])],None),([dict(track,forced=None)],None),([track],{'subtitleLanguage':'es'}),([track],{'showForced':False}),([track],{'preferSdh':True})):
            with self.subTest(tracks=tracks,preferences=prefs):
                self.assertIsNone(self.default_choice(tracks,preferences=prefs))
        self.assertIsNotNone(self.default_choice([track],preferences={'subtitleLanguage':'eng','showForced':True}))

    def test_derived_default_receipt_keeps_codec_language_source_and_forced_identity(self):
        for field,value in (('codec','webvtt'),('language','fr'),('source','external'),('forced',True)):
            def drift(wire,decision):
                decision['playback_plan']['subtitle']['inventory'][1][field]=value
            with self.subTest(field=field):
                result=self.start(drift,{'subtitleMode':'always','subtitleTrackId':None,'subtitleTrackIndex':None})
                self.assertFalse(result['outcome']['ok'])
                self.assertEqual('receipt_subtitle_selection',result['outcome']['startAttempts'][-1]['validationReason'])
                self.assertEqual([],result['downloads'])

    def test_default_language_mismatch_refuses_before_stock_allocation(self):
        result=self.start(options={'subtitleMode':'always','subtitleTrackId':None,'subtitleTrackIndex':None,'subtitlePreferences':{'subtitles':'always','subtitleLanguage':'es'}})
        self.assertFalse(result['outcome']['ok'])
        self.assertEqual('subtitle_selection_unsupported',result['outcome']['errorCode'])
        self.assertFalse(any(request['method']=='POST' for request in result['requests']))
        self.assertEqual([],result['downloads'])
