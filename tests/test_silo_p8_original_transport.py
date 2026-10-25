"""Private P8 activation at HTTP start/replan seams; shipping switches stay off."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from tools.brightscript import run_function
from tests import test_silo_playback_task as legacy
from tests import test_silo_original_transport as original
from tests import test_silo_original_p8_policy as p8
ROOT=Path(__file__).resolve().parents[1]

class SiloP8OriginalTransportTests(unittest.TestCase):
    def inputs(self):
        session,wire,decision=original.SiloOriginalTransportTests().inputs()
        f=p8.SiloOriginalP8PolicyTests().fixture()
        wire['versions']=[f['freshFile']['wire']]
        wire['versions'][0]['subtitle_tracks']=[]
        raw=decision['playback_plan']
        raw['source'].update(video_level=150,dolby_vision_profile=8,dv_bl_compat_id=1,dv_enhancement_layer='none',audio_codec='eac3')
        raw['effective_recipe']['audio_codec']='eac3'
        raw['selected_tracks']['audio']={'id':'file:731:audio:0','index':0}
        return session,wire,decision

    def worker(self,session,wire,decision,*,active=True,options=None,config=None):
        config=config or {}
        cap=json.loads((legacy.FIXTURES/'playback_capabilities.json').read_text())
        cap['installation_id']='server-install'
        cap['features']=config.get('features',[])
        cap.update(config.get('capability',{}))
        if cap['features']:cap['deliveries'].append('server_remux_hls')
        responses=[{'statusCode':200,'body':json.dumps(x)} for x in (wire,cap,decision)]
        if 'replan' in config:
            if 'audioChange' in config:responses.append({'statusCode':200,'body':json.dumps(wire)})
            responses.append({'statusCode':200,'body':json.dumps(cap)})
            if not config.get('failure') and 'audioChange' not in config:responses.append({'statusCode':200,'body':json.dumps(wire)})
            responses.append({'statusCode':200,'body':json.dumps(config['replan'])})
        responses.append({'statusCode':200,'body':'{"outcome":"stopped"}'})
        boundary=legacy.BOUNDARIES.replace('return {major:"15",minor:"3",revision:"4",build:"2402"}', 'return GetGlobalAA().testOS')
        boundary=boundary.replace('return "C000X"','if m.runtimeModel<>invalid then return m.runtimeModel\n        return "C000X"').replace('return {ModelNumber:"C208X"}','if m.runtimeNumber<>invalid then return {ModelNumber:m.runtimeNumber}\n        return {ModelNumber:"C208X"}')
        boundary=boundary.replace('if m.rejectMain10 = true', 'if m.rejectVideoContainer<>invalid and format.container=m.rejectVideoContainer then return {result:false}\n        if m.rejectMain10 = true')
        boundary=boundary.replace('format.chcnt<=2 and format.codec="aac"','(format.chcnt<=2 and format.codec="aac") or (format.codec="ac3" and format.chcnt=6)')
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            api=root/'api.brs'
            api.write_text((ROOT/'components/ApiTask.brs').read_text().replace('function TaskUniqueId(','function UnusedTaskUniqueId(',1).replace('function TaskRokuSiloContext(','function UnusedTaskRokuSiloContext(',1).replace('CreateObject("roDeviceInfo")','FixtureSiloDevice()'))
            http=root/'http.brs';http.write_text((ROOT/'source/network/Http.brs').read_text().replace('function HttpRequest(','function UnusedHttpRequest(',1))
            policy=root/'original.brs';source=(ROOT/'source/core/SiloOriginalPlaybackPolicy.brs').read_text()
            if active:
                source=source.replace('function SiloP8OriginalActivationEnabled(','function ShippingDisabledSiloP8OriginalActivationEnabled(',1)
                source+='\nfunction SiloP8OriginalActivationEnabled() as Boolean\n return true\nend function\n'
            policy.write_text(source)
            files=[api,http,policy,ROOT/'source/core/SiloUIPlaybackChoicesPolicy.brs']
            for path in legacy.FILES:
                if path.name=='SiloOriginalPlaybackPolicy.brs':continue
                target=root/path.name;target.write_text(path.read_text().replace('CreateObject("roDeviceInfo")','FixtureSiloDevice()'));files.append(target)
            bridge=root/'bridge.brs'
            bridge.write_text(boundary+'''
function P8Start(session as Object,wire as Object,responses as Object,options as Object,config as Object) as Object
 GetGlobalAA().testOS={major:"16",minor:"0",revision:"4",build:"834"}
 if config.p7=true then GetGlobalAA().testOS={major:"15",minor:"3",revision:"4",build:"2402"}
 decoded=DecodeSiloResponse("detail",FormatJson(wire),{sourceId:session.sourceId})
 detail=ScopeCatalogData(decoded.data,session.sourceId)
 if config.initialAudio<>invalid
  for each key in config.initialAudio
   detail.versions[0].audioTracks[0][key]=config.initialAudio[key]
  end for
 end if
 params={itemId:"fixture-item",fileId:"731",detail:detail,qualityPreference:"original",qualityExplicit:false}
 for each key in options
  params[key]=options[key]
 end for
 device=FixtureSiloDevice():device.videoMode="2160p60"
 if config.runtimeDevice=true then device.runtimeModel="runtime-device":device.runtimeNumber="runtime-number":GetGlobalAA().testOS={major:"17",minor:"0",revision:"1",build:"100"}
 if config.rejectVideo=true then device.rejectMain10=true
 if config.rejectVideoContainer<>invalid then device.rejectVideoContainer=config.rejectVideoContainer
 if config.rejectOutput=true then device.displayUnknown=true
 if config.probeContext<>invalid
  scope={provider:"silo",sourceId:session.sourceId,profileId:session.profileId,generation:0}
  if config.ordinaryJob=true then m.top={job:{action:"playback_start",provider:"silo",sourceId:scope.sourceId,profileId:scope.profileId,generation:0}}
  candidate=TaskSiloOriginalCandidate(wire,session,"731",params,device,"attempt-fixture-01",scope,config.probeContext)
  return {candidate:candidate}
 end if
 if config.probe=true
  m.requests=[]:m.timeouts=[]:m.responses=responses:m.fixtureRevision=0:m.changeRevision=false:m.fixtureSession=session
  probeParams={itemId:params.itemId,fileId:params.fileId,detail:params.detail}
  for each key in ["audioTrackId","audioTrackIndex"]
   if params.DoesExist(key) then probeParams[key]=params[key]
  end for
  probed=ExecuteApiAction("silo","experimental_playback_probe",probeParams,{sourceId:session.sourceId,profileId:session.profileId})
  return {outcome:probed,requests:m.requests}
 end if
 if config.noDetail=true then params.Delete("detail")
 started=RunSiloPlaybackStart(session,params,responses,false)
 if started.outcome.ok<>true or config.replan=invalid then return started
 plan=started.outcome.plan
 scope={provider:"silo",sourceId:session.sourceId,profileId:session.profileId,generation:0}
 params={sessionId:plan.sessionId,plan:plan,qualityPreference:"original",positionMs:12500,replanRequestId:"request-fixture-0002"}
 if config.failure=true then params["failureClassification"]="decoder_failure"
 if config.audioChange<>invalid
  params.Delete("qualityPreference")
  params["audioTrackIndex"]=config.audioChange
  result=TaskSelectSiloAudio(session,params,scope,0)
 else
  result=TaskReplanSiloPlayback(session,params,scope,0)
 end if
 return {outcome:result,requests:m.requests}
end function
''')
            files.append(bridge)
            return run_function(files,'P8Start',[session,wire,responses,options or {},config],root=root)

    def body(self,result,index=2):return json.loads(result['requests'][index]['body'])
    def claims(self,result,index=2):return self.body(result,index)['client_playback_context']['deliveries']['original_http']['validated_claims']

    def test_private_p8_unpatched_default_eac3_claims_and_owned_descriptor(self):
        result=self.worker(*self.inputs())
        self.assertTrue(result['outcome']['ok'],result['outcome'])
        self.assertEqual(['client_managed_dynamic_range_v1'],self.claims(result))
        self.assertEqual(0,self.body(result)['audio_track_index'])
        descriptor=result['outcome']['plan']['originalPlayback']
        self.assertEqual(('731','session-fixture-01','eac3',0),(descriptor['fileId'],descriptor['sessionId'],descriptor['audioIdentity']['codec'],descriptor['audioIdentity']['index']))
        self.assertNotIn(8,self.body(result)['client_capabilities']['hdr_details']['dolby_vision_profiles'])

    def test_p8_disabled_and_p7_legacy_disabled_emit_no_original_claims(self):
        for p7 in (False,True):
            args=self.inputs() if not p7 else original.SiloOriginalTransportTests().inputs()
            args[2]['playback_plan'].pop('decision_reason')
            result=self.worker(*args,active=p7,config={'p7':p7})
            self.assertEqual([],self.claims(result))
            self.assertNotIn('originalPlayback',result['outcome'].get('plan',{}))

    def test_private_p8_explicit_ac3_keeps_source_ordinal(self):
        session,wire,decision=self.inputs()
        wire['versions'][0]['audio_tracks'][0]['codec']='dts'
        wire['versions'][0]['audio_tracks'].append(dict(codec='ac3',language='en',channels=6,layout='5.1(side)',default=False))
        raw=decision['playback_plan'];raw['source']['audio_codec']='ac3';raw['effective_recipe']['audio_codec']='ac3';raw['selected_tracks']['audio']={'id':'file:731:audio:1','index':1}
        result=self.worker(session,wire,decision,options={'audioTrackIndex':1})
        self.assertTrue(result['outcome']['ok'],result['outcome'])
        self.assertEqual(['client_managed_dynamic_range_v1','client_selected_audio_track_v1'],self.claims(result))
        self.assertEqual(1,self.body(result)['audio_track_index'])

    def test_false_output_source_decoder_and_audio_proof_emit_no_claim(self):
        for case in ('output','source','decoder','audio'):
            session,wire,decision=self.inputs();config={}
            decision['playback_plan'].pop('decision_reason')
            if case=='output':config['rejectOutput']=True
            if case=='decoder':config['rejectVideo']=True
            if case=='source':wire['versions'][0]['video_tracks'][0]['dv_el_present']=True
            if case=='audio':wire['versions'][0]['audio_tracks'][0]['codec']='dts'
            result=self.worker(session,wire,decision,config=config)
            self.assertEqual([],self.claims(result),case)

    def test_normalized_detail_audio_id_becomes_canonical_only_after_fresh_proof(self):
        result=self.worker(*self.inputs(),options={'audioTrackIndex':0,'audioTrackId':'0'})
        self.assertTrue(result['outcome']['ok'],result['outcome'])
        self.assertEqual(['client_managed_dynamic_range_v1'],self.claims(result))
        self.assertEqual('file:731:audio:0',self.body(result)['audio_track_id'])

    def test_ordinary_hls_must_acknowledge_fresh_explicit_audio_or_release_allocation(self):
        for returned in (None, {'id':'file:731:audio:1','index':0},
                         {'id':'file:731:audio:0','index':1}):
            with self.subTest(returned=returned):
                session,wire,decision=self.inputs()
                wire['versions'][0]['audio_tracks'].append(
                    dict(codec='ac3',language='en',channels=6,layout='5.1(side)',default=False))
                decision=original.SiloOriginalTransportTests().ordinary_hls(decision)
                if returned is None:
                    decision['playback_plan']['selected_tracks'].pop('audio')
                else:
                    decision['playback_plan']['selected_tracks']['audio']=returned
                result=self.worker(session,wire,decision,active=False,
                    options={'audioTrackIndex':1,'audioTrackId':'file:731:audio:1'},
                    config={'features':['native_hls_mpegts_v1']})
                self.assertFalse(result['outcome']['ok'])
                self.assertEqual('invalid_response',result['outcome']['errorCode'])
                self.assertEqual(['GET','GET','POST','DELETE'],[r['method'] for r in result['requests']])
                cleanup=json.loads(result['requests'][-1]['body'])
                self.assertEqual({'installation_id':'server-install',
                    'stop_id':'10000000-0000-4000-8000-000000000001'},cleanup)
                self.assertNotIn('plan',result['outcome'])

    def test_matching_ordinary_hls_accepts_ui_canonical_ordinal_with_different_wire_index(self):
        session,wire,decision=self.inputs()
        wire['versions'][0]['audio_tracks'][0]['index']=3
        decision=original.SiloOriginalTransportTests().ordinary_hls(decision)
        result=self.worker(session,wire,decision,active=False,
            options={'audioTrackIndex':0,'audioTrackId':'file:731:audio:0'},
            config={'features':['native_hls_mpegts_v1']})
        self.assertTrue(result['outcome']['ok'],result['outcome'])
        self.assertEqual(['GET','GET','POST'],[r['method'] for r in result['requests']])
        self.assertEqual(0,self.body(result)['audio_track_index'])
        self.assertEqual('file:731:audio:0',self.body(result)['audio_track_id'])
        self.assertEqual({'index':0,'id':'file:731:audio:0'},
            result['outcome']['plan']['siloPlayback']['selectedTracks']['audio'])
        self.assertNotIn('originalPlayback',result['outcome']['plan'])

    def test_explicit_old_detail_audio_drift_refuses_before_capabilities_or_allocation(self):
        for field,value in [('language','fr'),('codec','ac3'),('channels',2),('layout','stereo'),('id','changed'),('sourceOrdinal',1)]:
            result=self.worker(*self.inputs(),options={'audioTrackIndex':0,'audioTrackId':'0'},config={'initialAudio':{field:value}})
            self.assertEqual({'ok':False,'errorCode':'invalid_audio_selection'},result['outcome'],field)
            self.assertEqual(['GET'],[r['method'] for r in result['requests']],field)

    def test_legacy_public_opaque_id_and_wire_index_are_preserved(self):
        for options in ({'audioTrackId':'source-track'},{'audioTrackIndex':7,'audioTrackId':'7'}):
            session,wire,decision=self.inputs()
            wire['versions'][0]['audio_tracks'][0]['index']=7
            decision['playback_plan'].pop('decision_reason')
            result=self.worker(session,wire,decision,options=options)
            # Opaque selectors remain unchanged; they grant no Original DV proof.
            self.assertFalse(result['outcome']['ok'])
            self.assertEqual('unsupported_stream',result['outcome']['errorCode'])
            self.assertTrue(result['outcome']['cleanupLeaseClosed'])
            self.assertEqual(['GET','GET','POST','DELETE'],[r['method'] for r in result['requests']])
            body=self.body(result)
            self.assertEqual(options.get('audioTrackId'),body.get('audio_track_id'))
            if 'audioTrackIndex' in options:self.assertEqual(7,body['audio_track_index'])
            self.assertEqual([],self.claims(result))

    def test_numeric_id_and_source_ordinal_cannot_reinterpret_ambiguous_wire_index(self):
        session,wire,decision=self.inputs()
        wire['versions'][0]['audio_tracks'][0]['index']=7
        result=self.worker(session,wire,decision,options={'audioTrackIndex':0,'audioTrackId':'7'})
        self.assertEqual({'ok':False,'errorCode':'invalid_audio_selection'},result['outcome'])
        self.assertEqual(['GET'],[r['method'] for r in result['requests']])

    def test_proven_native_dv_hls_copy_precedes_original_but_disabled_route_does_not(self):
        context={'deliveries':{'hls':{'enabled':True,'supported_on_device':True,'features':['native_hls_separate_audio_v1'],
                 'video_codecs':['hevc'],'audio_decode_codecs':[], 'audio_passthrough_codecs':['eac3'],
                 'hdr_details':{'dolby_vision_profile_levels':[{'profile':8,'max_level':6,'bl_compatibility_ids':[1]}]}}}}
        args=self.inputs()
        # Omitted official false is still a qualified P8 base, without changing wire facts.
        del args[1]['versions'][0]['video_tracks'][0]['dv_el_present']
        result=self.worker(*args,config={'probeContext':context})
        self.assertIsNone(result['candidate'])
        for change in ('disabled','no-profile','feature-only','audio','video-container'):
            changed=copy.deepcopy(context)
            if change=='disabled':changed['deliveries']['hls']['enabled']=False
            if change=='no-profile':changed['deliveries']['hls']['hdr_details']['dolby_vision_profile_levels']=[]
            if change=='feature-only':changed['deliveries']['hls'].pop('hdr_details')
            if change=='audio':changed['deliveries']['hls']['audio_passthrough_codecs']=[]
            result=self.worker(*args,config={'probeContext':changed,
                'rejectVideoContainer':'mp4' if change=='video-container' else None})
            self.assertEqual(['client_managed_dynamic_range_v1'],result['candidate']['claims'],change)

    def test_negotiated_copy_without_hevc_allows_qualified_ordinary_original(self):
        context={'deliveries':{'hls':{'enabled':True,'supported_on_device':True,
            'features':['native_hls_mpegts_v1'],'video_codecs':['h264'],
            'audio_decode_codecs':['aac'],'audio_passthrough_codecs':[],
            'hdr_details':{'hdr10':True}}}}
        result=self.worker(*self.inputs(),active=False,options={'subtitleMode':'off'},
            config={'probeContext':context,'ordinaryJob':True})
        self.assertEqual(['client_managed_dynamic_range_v1'],result['candidate']['claims'])

    def test_current_copy_eligibility_preserves_priority_and_excludes_unusable_lanes(self):
        context={'deliveries':{'hls':{'enabled':True,'supported_on_device':True,
            'features':['native_hls_separate_audio_v1'],'video_codecs':['hevc'],
            'audio_decode_codecs':[],'audio_passthrough_codecs':['eac3'],
            'hdr_details':{'hdr10':True}}}}
        for change,preferred in [('usable',True),('disabled',False),('unsupported',False),('audio',False),('video-container',False)]:
            changed=copy.deepcopy(context);hls=changed['deliveries']['hls']
            if change=='disabled':hls['enabled']=False
            if change=='unsupported':hls['supported_on_device']=False
            if change=='audio':hls['audio_passthrough_codecs']=[]
            result=self.worker(*self.inputs(),active=False,options={'subtitleMode':'off'},
                config={'probeContext':changed,'ordinaryJob':True,
                        'rejectVideoContainer':'mp4' if change=='video-container' else None})
            if preferred:self.assertIsNone(result['candidate'],change)
            else:self.assertEqual(['client_managed_dynamic_range_v1'],result['candidate']['claims'],change)

    def test_malformed_negotiated_copy_context_cannot_mint_ordinary_claims(self):
        context={'deliveries':{'hls':{'enabled':True,'supported_on_device':True,
            'features':['native_hls_mpegts_v1'],'video_codecs':'hevc',
            'audio_decode_codecs':['aac'],'audio_passthrough_codecs':[],
            'hdr_details':{'hdr10':True}}}}
        for malformed in (context,{}, {'deliveries':{'hls':None}}):
            result=self.worker(*self.inputs(),active=False,options={'subtitleMode':'off'},
                config={'probeContext':malformed,'ordinaryJob':True})
            self.assertIsNone(result['candidate'])

    def test_explicit_ac3_change_preserves_fresh_guarded_owner(self):
        session,wire,decision=self.inputs()
        wire['versions'][0]['audio_tracks'].append(dict(codec='ac3',language='en',channels=6,layout='5.1(side)',default=False))
        replan=copy.deepcopy(decision);raw=replan['playback_plan']
        raw.update(plan_id='plan-fixture-02',plan_attempt_key='opaque-attempt-key-02')
        raw['source']['audio_codec']='ac3';raw['effective_recipe']['audio_codec']='ac3'
        raw['selected_tracks']['audio']={'id':'file:731:audio:1','index':1}
        result=self.worker(session,wire,decision,config={'replan':replan,'audioChange':1})
        self.assertTrue(result['outcome']['ok'],result['outcome'])
        descriptor=result['outcome']['plan']['originalPlayback']
        self.assertEqual(('session-fixture-01','ac3',1),(descriptor['sessionId'],descriptor['audioIdentity']['codec'],descriptor['audioIdentity']['index']))
        self.assertEqual(['client_managed_dynamic_range_v1','client_selected_audio_track_v1'],self.claims(result,-1))

    def test_p8_seek_requalifies_but_decoder_failure_withdraws_original(self):
        session,wire,decision=self.inputs();replan=copy.deepcopy(decision)
        replan['playback_plan'].update(plan_id='plan-fixture-02',plan_attempt_key='opaque-attempt-key-02')
        result=self.worker(session,wire,decision,config={'replan':replan})
        self.assertTrue(result['outcome']['ok'],result['outcome'])
        self.assertEqual(['client_managed_dynamic_range_v1'],self.claims(result,-1))
        self.assertEqual('session-fixture-01',result['outcome']['plan']['originalPlayback']['sessionId'])
        result=self.worker(session,wire,decision,config={'replan':replan,'failure':True})
        self.assertFalse(result['outcome']['ok'])
        self.assertEqual([],self.claims(result,-1))

if __name__=='__main__':unittest.main()
