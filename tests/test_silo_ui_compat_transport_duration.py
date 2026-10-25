"""Actual Scene remote-key/paint→owned seek HTTP; SDK rendering fields only."""
import json
import unittest
from tests import test_silo_compat_continuation as task
from tests import test_silo_compat_playback_task as holder
from tests.test_silo_single_source_compat_flow import single_source
from tests.test_silo_modern_compat_flow import modern_device

SEEK_SETUP='m.transport=CreateObject("roSGNode","Group"):m.transport.visible=false:m.transportTimer={control:"stop"}:m.transportEnabled=true:m.transportPreviewMs=900000:m.transportOffsetMs=0'
RENDER='''m.transport=CreateObject("roSGNode","Group"):m.transport.visible=false:m.transportTimer={control:"stop"}:m.transportEnabled=true:m.transportPreviewMs=invalid:m.transportOffsetMs=0:m.transportIndex=0:m.transportRepeats=0
   for each field in ["transportTitle","transportTime","transportHint"]
    m[field]=m.top.createChild("Label")
   end for
   m.transportActions=m.top.createChild("Group"):m.transportProgress=m.top.createChild("Rectangle")
   pills=[]
   for i=0 to 3
    pills.Push({bg:m.top.createChild("Poster"),label:m.top.createChild("Label")})
   end for
   m.pillGroups.transportActions={pills:pills,index:0}
   m.video.duration=14
   ignored=onKeyEvent("fastforward",true):ignored=onKeyEvent("fastforward",true)
   device=FixtureSiloDevice():beforeVideo=device.videoQueries.Count():beforeAudio=device.audioQueries.Count():beforeHttp=m.requests.Count():beforeDevice=GetGlobalAA().fixtureDeviceCalls
   for i=1 to 5
    TransportPaint()
   end for
   m.fixtureTransportProbe={duration:TransportDuration(),preview:m.transportPreviewMs,text:m.transportTime.text,videoDelta:device.videoQueries.Count()-beforeVideo,audioDelta:device.audioQueries.Count()-beforeAudio,httpDelta:m.requests.Count()-beforeHttp,deviceDelta:GetGlobalAA().fixtureDeviceCalls-beforeDevice}
'''

class CompatTransportDuration(unittest.TestCase):
    def scene(self,catalog=0,start=1000,drift='',control='media_seek'):
        def source(wire,decision):
            single_source(wire,decision);wire['versions'][0]['duration']=6506
        envelope=task.CompatContinuation().job(device=modern_device(),mutate=source,options={'startPositionMs':start})['outcome']
        self.assertEqual('compat_prepare_required',envelope.get('errorCode'))
        _,wire,decision=task.CompatContinuation().fixture();source(wire,decision)
        keys='   ignored=onKeyEvent("fastforward",true):ignored=onKeyEvent("fastforward",true)'
        render=RENDER.replace(keys,'   '+drift+'\n'+keys) if drift else RENDER
        sdk={SEEK_SETUP:render,
             'function FixtureSiloDevice() as Object\n':'function FixtureSiloDevice() as Object\n GetGlobalAA().fixtureDeviceCalls=NumberOr(GetGlobalAA().fixtureDeviceCalls,0)+1\n',
             'return "0"':'if GetGlobalAA().fixtureStaleRevision=true then return "1"\n return "0"',
             'title:"Fixture",durationMs:7200000}':'title:"Fixture",durationMs:'+str(catalog)+'}',
             'startPositionMs:25000':'startPositionMs:'+str(start),
             'ignored=TransportKey("OK")\n   m.video.state="stopped":onVideoState():m.top=parent\n   return invalid':'ignored=onKeyEvent("OK",true)\n   m.video.state="stopped":onVideoState():m.top=parent\n   if parent.command.action<>"seek" then m.fixtureBoundaryEnded=true:throw "finite SDK declined-seek checkpoint"\n   return invalid',
             'return {scene:{holderCreated:true,':'return {transportProbe:m.fixtureTransportProbe,transportAfter:TransportDuration(),scene:{holderCreated:true,'}
        return holder.CompatPlaybackTask().transcript(scene=dict(envelope=envelope,wire=wire,control=control),device_overrides=modern_device(),sdk_overrides=sdk)

    def test_two_forward_keys_use_full_selected_duration_and_reanchor_at_twenty_one_seconds(self):
        result=self.scene()
        posts=[json.loads(q['body']) for q in result['requests'] if q['url'].endswith('/PlaybackInfo')]
        self.assertEqual([10000000,210000000],[q['StartTimeTicks'] for q in posts])
        self.assertEqual(2,result['scene']['plan']['planGeneration'])
        self.assertEqual(dict(duration=6506000,preview=21000,text='0:21 / 108:26',videoDelta=0,audioDelta=0,httpDelta=0,deviceDelta=0),result['transportProbe'])

    def test_short_catalog_does_not_refuse_a_valid_source_range_seek(self):
        result=self.scene(catalog=10000)
        posts=[json.loads(q['body']) for q in result['requests'] if q['url'].endswith('/PlaybackInfo')]
        self.assertEqual([10000000,210000000],[q['StartTimeTicks'] for q in posts])
        self.assertEqual(2,result['scene']['plan']['planGeneration'])

    def test_long_catalog_seek_clamps_to_selected_source_end(self):
        result=self.scene(catalog=7200000,start=6500000)
        posts=[json.loads(q['body']) for q in result['requests'] if q['url'].endswith('/PlaybackInfo')]
        self.assertEqual([65000000000,65050000000],[q['StartTimeTicks'] for q in posts])
        self.assertEqual(6506000,result['transportProbe']['duration'])
        self.assertEqual(6505000,result['transportProbe']['preview'])

    def test_stale_local_owner_token_revision_or_native_content_refuses_cached_range(self):
        changes=['m.profileId="other-profile"','m.playToken++',
                 'GetGlobalAA().fixtureStaleRevision=true',
                 'm.video.content=CreateObject("roSGNode","ContentNode")']
        for drift in changes:
            with self.subTest(drift=drift):
                result=self.scene(catalog=7200000,drift=drift)
                self.assertEqual(0,result['transportProbe']['duration'])
                self.assertEqual(0,result['transportProbe']['videoDelta'])
                self.assertEqual(0,result['transportProbe']['audioDelta'])
                self.assertEqual(0,result['transportProbe']['deviceDelta'])
                self.assertEqual(0,result['transportProbe']['httpDelta'])
                self.assertEqual(1,sum(q['url'].endswith('/PlaybackInfo') for q in result['requests']))
                self.assertFalse(result['scene']['released'])

    def test_new_generation_duration_survives_delayed_old_binding_callback(self):
        result=self.scene(control='media_oldgen')
        self.assertTrue(result['scene']['oldGenerationPreserved'])
        self.assertEqual(2,result['scene']['plan']['planGeneration'])
        self.assertEqual(6506000,result['transportAfter'])
        posts=[json.loads(q['body']) for q in result['requests'] if q['url'].endswith('/PlaybackInfo')]
        self.assertEqual([10000000,210000000],[q['StartTimeTicks'] for q in posts])

    def test_noncompatibility_catalog_and_native_offset_fallback_stay_unchanged(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from tools.brightscript import run_brightscript
        root=Path(__file__).resolve().parents[1]
        with TemporaryDirectory() as td:
            text=run_brightscript([root/'components/SiloUITransport.brs',root/'source/core/SiloUIFormat.brs'],'''
                m.playPlan={transport:"native",timelineOffsetMs:5000}
                m.playItem={durationMs:60000}:m.video={duration:14}
                catalog=TransportDuration():m.playItem.durationMs=0
                print FormatJson({catalog:catalog,fallback:TransportDuration()})
            ''',root=Path(td))
        self.assertEqual(dict(catalog=60000,fallback=19000),json.loads(text))
