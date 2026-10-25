"""Real-film HDR10 base original route at the ordinary Task/receipt boundary."""
import unittest
from tests import test_silo_ordinary_p8_original as ordinary

class Real4KOriginal(unittest.TestCase):
    def test_pinned_24fps_p8_eac3_uses_fresh_default_audio_on_build842(self):
        def musical(wire,decision):
            file=wire['versions'][0]
            file['audio_tracks']=[dict(codec='eac3',language='en',channels=6,layout='5.1(side)',default=True)]
            file['codec_audio']='eac3';file['effective_audio_track_index']=0
            file['video_tracks'][0]['frame_rate']='24/1'
            raw=decision['playback_plan']
            for section in ('source','effective_recipe'):
                raw[section].update(audio_codec='eac3',audio_channels=6,audio_layout='5.1(side)',frame_rate=24)
            raw['selected_tracks']['audio']={'id':'file:731:audio:0','index':0}
        result=ordinary.OrdinaryP8Original().start(mutate=musical,options={'audioTrackId':None,'audioTrackIndex':None},device={'build:"834"':'build:"842"','format.chcnt<=2 and (format.codec="aac" or format.codec="ac3")':'format.chcnt<=6 and (format.codec="aac" or format.codec="ac3" or format.codec="eac3")'})
        body=ordinary.OrdinaryP8Original().body(result)
        self.assertEqual(['client_managed_dynamic_range_v1'],body['client_playback_context']['deliveries']['original_http']['validated_claims'])
        self.assertTrue(result['outcome']['ok'],result['outcome'])
        self.assertEqual('hdr10_base_original_v1',result['outcome']['plan']['originalPlayback']['qualifiedRoute'])
        self.assertEqual(0,body['audio_track_index'])
        self.assertFalse(body['allow_alternate_versions'])
        self.assertNotIn(8,body['client_playback_context']['deliveries']['hls']['hdr_details']['dolby_vision_profiles'])

    def test_pinned_p7_ac3_keeps_explicit_source_ordinal_on_build842(self):
        def p7(wire,decision):
            file=wire['versions'][0]
            file['audio_tracks']=[dict(codec='truehd',language='en',channels=8,layout='7.1',default=True),dict(codec='ac3',language='en',channels=6,layout='5.1',default=False)]
            video=file['video_tracks'][0]
            video.update(dv_profile=7,dv_bl_compat_id=6,dv_el_present=True,dv_enhancement_layer='unknown',level=153)
            raw=decision['playback_plan']
            for section in ('source','effective_recipe'):
                raw[section].update(audio_channels=6,audio_layout='5.1')
            raw['source'].update(video_level=153,dolby_vision_profile=7,dv_bl_compat_id=6,dv_enhancement_layer='unknown')
        result=ordinary.OrdinaryP8Original().start(mutate=p7,device={'build:"834"':'build:"842"','format.chcnt<=2 and (format.codec="aac" or format.codec="ac3")':'format.chcnt<=6 and (format.codec="aac" or format.codec="ac3")'})
        body=ordinary.OrdinaryP8Original().body(result)
        self.assertTrue(result['outcome']['ok'],result['outcome'])
        descriptor=result['outcome']['plan']['originalPlayback']
        self.assertEqual(('hdr10_base_original_v1',7,1),(descriptor['qualifiedRoute'],descriptor['dolbyVisionProfile'],descriptor['audioIdentity']['index']))
        self.assertEqual('file:731:audio:1',body['audio_track_id'])
        from tools.brightscript import run_function
        from pathlib import Path
        root=Path(__file__).resolve().parents[1]
        policy=root/'source/core/SiloUIOriginalPlaybackPolicy.brs'
        self.assertTrue(run_function([policy],'SiloUIOriginalQualifiedFilm',[descriptor]))
        import copy
        for field,value in [('outputFingerprint','C000X/C208X/16.0.4.843/2160p60/hdr10'),('dolbyVisionProfile',5)]:
            changed=copy.deepcopy(descriptor);changed[field]=value
            self.assertFalse(run_function([policy],'SiloUIOriginalQualifiedFilm',[changed]))
        malformed=copy.deepcopy(descriptor);malformed['videoFacts']['profile']={}
        self.assertFalse(run_function([policy],'SiloUIOriginalQualifiedFilm',[malformed]))
        state=run_function([policy],'SiloUIOriginalCreate',[descriptor,7,3,0])
        event=dict(kind='tick',token=7,generation=3,nowMs=43707,nativeState='buffering')
        self.assertIsNone(run_function([policy],'SiloUIOriginalReduce',[state,event])['command'])
        event['nowMs']=60000
        self.assertEqual('startup_timeout',run_function([policy],'SiloUIOriginalReduce',[state,event])['command']['reason'])

    def foreign_film(self, profile=8, language='fra', *, other_language=None, width=3840, height=2160):
        def mutate(wire, decision):
            file=wire['versions'][0]
            codec='eac3' if profile==8 else 'ac3'
            file['audio_tracks']=[dict(codec=codec,language=language,channels=6,layout='5.1',default=True)]
            if other_language is not None:
                file['audio_tracks'].insert(0,dict(codec='truehd',language=other_language,channels=8,layout='7.1',default=True))
                file['audio_tracks'][1]['default']=False
            file.update(codec_audio=file['audio_tracks'][0]['codec'],effective_audio_track_index=0)
            video=file['video_tracks'][0]
            video.update(width=width,height=height)
            if profile==7:
                video.update(dv_profile=7,dv_bl_compat_id=6,dv_el_present=True,dv_enhancement_layer='unknown',level=153)
            raw=decision['playback_plan']
            for section in ('source','effective_recipe'):
                raw[section].update(audio_codec=codec,audio_channels=6,audio_layout='5.1',width=width,height=height)
            if profile==7:
                raw['source'].update(video_level=153,dolby_vision_profile=7,dv_bl_compat_id=6,dv_enhancement_layer='unknown')
            index=1 if other_language is not None else 0
            raw['selected_tracks']['audio']={'id':f'file:731:audio:{index}','index':index}
        return ordinary.OrdinaryP8Original().start(mutate=mutate,options={'audioTrackId':None,'audioTrackIndex':None},device={'format.chcnt<=2 and (format.codec="aac" or format.codec="ac3")':'format.chcnt<=6 and (format.codec="aac" or format.codec="ac3" or format.codec="eac3")'})

    def test_foreign_film_claim_receipt_and_native_inventory_keep_source_language(self):
        from tools.brightscript import run_function
        from pathlib import Path
        policy=Path(__file__).resolve().parents[1]/'source/core/SiloUIOriginalPlaybackPolicy.brs'
        for profile,language,canonical in [(8,'fra','fr'),(7,'spa','es'),(8,'jpn','ja')]:
            with self.subTest(profile=profile,language=language):
                result=self.foreign_film(profile,language)
                body=ordinary.OrdinaryP8Original().body(result)
                self.assertEqual(['client_managed_dynamic_range_v1'],body['client_playback_context']['deliveries']['original_http']['validated_claims'])
                self.assertTrue(result['outcome']['ok'],result['outcome'])
                descriptor=result['outcome']['plan']['originalPlayback']
                self.assertEqual(('hdr10_base_original_v1',canonical,0),(descriptor['qualifiedRoute'],descriptor['audioIdentity']['language'],descriptor['audioIdentity']['index']))
                self.assertTrue(run_function([policy],'SiloUIOriginalQualifiedFilm',[descriptor]))
                state=run_function([policy],'SiloUIOriginalCreate',[descriptor,7,3,0])
                inventory=[dict(Track='foreign-native',Format=descriptor['audioIdentity']['codec'],Language=language)]
                event=dict(kind='inventory',token=7,generation=3,nowMs=1000,inventory=inventory)
                self.assertEqual({'kind':'select','trackId':'foreign-native'},run_function([policy],'SiloUIOriginalReduce',[state,event])['command'])

    def test_cropped_uhd_start_receipt_and_ui_keep_the_qualified_source(self):
        from tools.brightscript import run_function
        from pathlib import Path
        policy=Path(__file__).resolve().parents[1]/'source/core/SiloUIOriginalPlaybackPolicy.brs'
        result=self.foreign_film(width=3834,height=1602)
        self.assertTrue(result['outcome']['ok'],result['outcome'])
        descriptor=result['outcome']['plan']['originalPlayback']
        self.assertEqual(('hdr10_base_original_v1',3834,1602),
                         (descriptor['qualifiedRoute'],descriptor['videoFacts']['width'],descriptor['videoFacts']['height']))
        self.assertEqual(['client_managed_dynamic_range_v1'],ordinary.OrdinaryP8Original().body(result)['client_playback_context']['deliveries']['original_http']['validated_claims'])
        self.assertTrue(run_function([policy],'SiloUIOriginalQualifiedFilm',[descriptor]))

    def test_qualified_film_width_bounds_agree_between_start_and_ui(self):
        import copy,json
        from pathlib import Path
        from tools.brightscript import run_function
        policy=Path(__file__).resolve().parents[1]/'source/core/SiloUIOriginalPlaybackPolicy.brs'
        result=self.foreign_film(width=1921,height=1602)
        descriptor=result['outcome']['plan']['originalPlayback']
        self.assertTrue(run_function([policy],'SiloUIOriginalQualifiedFilm',[descriptor]))
        for width in (1920,0,-1,3841,'3834',None,{},3834.5):
            with self.subTest(width=width):
                changed=copy.deepcopy(descriptor);changed['videoFacts']['width']=width
                self.assertFalse(run_function([policy],'SiloUIOriginalQualifiedFilm',[changed]))
                refused=self.foreign_film(width=width,height=1602)
                self.assertNotIn('originalPlayback',refused['outcome'].get('plan',{}))
                for request in refused['requests']:
                    if request['method']=='POST':
                        body=json.loads(request['body'])
                        self.assertEqual([],body['client_playback_context']['deliveries']['original_http']['validated_claims'])

    def test_malformed_or_unknown_language_cannot_advertise_original(self):
        for language in ('und','not-a-language',{},''):
            with self.subTest(language=language):
                result=self.foreign_film(language=language)
                self.assertEqual([],ordinary.OrdinaryP8Original().body(result)['client_playback_context']['deliveries']['original_http']['validated_claims'])
                self.assertNotIn('originalPlayback',result['outcome'].get('plan',{}))

    def test_truehd_substitution_requires_same_normalized_language(self):
        result=self.foreign_film(7,'spa',other_language='fra')
        self.assertEqual([],ordinary.OrdinaryP8Original().body(result)['client_playback_context']['deliveries']['original_http']['validated_claims'])
        self.assertNotIn('originalPlayback',result['outcome'].get('plan',{}))
        matched=self.foreign_film(7,'fra',other_language='fr')
        self.assertTrue(matched['outcome']['ok'],matched['outcome'])
        descriptor=matched['outcome']['plan']['originalPlayback']
        self.assertEqual(('fr',1),(descriptor['audioIdentity']['language'],descriptor['audioIdentity']['index']))
        self.assertEqual('file:731:audio:1',ordinary.OrdinaryP8Original().body(matched)['audio_track_id'])

    def test_foreign_scene_inventory_rejects_content_identity_drift(self):
        import json,tempfile
        from pathlib import Path
        from tools.brightscript import run_brightscript
        from tests.test_silo_ui_original_playback import descriptor,inventory
        proof=descriptor()
        proof['audioIdentity']['language']='fr'
        for audio in proof['sourceAudio']:audio['language']='fr'
        tracks=inventory()
        for audio in tracks:audio['Language']='fra'
        values=json.dumps([proof,tracks]).replace('"','""')
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            code='values=ParseJson("'+values+'")\n'+'''
 node={identity:"current",isSameNode:function(other as Object) as Boolean
  return m.identity=other.identity
 end function}
 m.originalPlayback=SiloUIOriginalCreate(values[0],7,3,0)
 m.playToken=7:m.originalGeneration=3:m.originalContent={identity:"retired"}
 m.originalDrained=true:m.originalFreshState=true:m.originalOutputFingerprint="output-1"
 m.video={content:node,state:"buffering",availableAudioTracks:values[1],audioTrack:"old",position:0,currentAudioTrack:"foreign-native",audioFormat:"ac3",mute:true}
 m.originalClock={TotalMilliseconds:function() as Integer
  return 1000
 end function}
 PlayerOriginalInventory()
 PlayerOriginalObserve()
 print FormatJson({track:m.video.audioTrack,phase:m.originalPlayback.phase,position:m.originalPlayback.playingPosition})
'''
            result=json.loads(run_brightscript([root/'source/core/SiloUIOriginalPlaybackPolicy.brs',root/'components/SiloUIPlayer.brs'],code,root=Path(directory)).strip())
        self.assertEqual({'track':'old','phase':'await_inventory','position':None},result)
