"""Ordinary explicit Detail-Audio P8 Original through actual runJob and HTTP.

SDK device/HTTP/session are substituted. The existing context wrapper delegates
to the actual function then clones repeated AA/array references solely for the
host FormatJson cycle bug. Both activation policies execute
unchanged. This pinned-file tracer establishes no automatic-version behavior.
"""
import copy,json,re,tempfile,unittest
from pathlib import Path
from tools.brightscript import run_function
from tests import test_silo_playback_task as legacy
from tests import test_silo_p8_original_transport as p8
ROOT=Path(__file__).resolve().parents[1]

class OrdinaryP8Original(unittest.TestCase):
    def inputs(self):
        session,wire,decision=p8.SiloP8OriginalTransportTests().inputs()
        file=wire['versions'][0]
        file['audio_tracks']=[dict(codec='dts',language='en',channels=6,layout='5.1',default=True),
                              dict(codec='ac3',language='en',channels=2,layout='stereo',default=False)]
        file['effective_audio_track_index']=0;file['codec_audio']='dts'
        raw=decision['playback_plan']
        for section in ('source','effective_recipe'):
            raw[section].update(audio_codec='ac3',audio_channels=2,audio_layout='stereo')
        raw['selected_tracks']['audio']={'id':'file:731:audio:1','index':1}
        return session,wire,decision

    def start(self,*,mutate=None,options=None,device=None,features=None,job=None,deliveries=None,subtitle_scenario=None):
        session,wire,decision=self.inputs()
        if mutate:mutate(wire,decision)
        cap=json.loads((legacy.FIXTURES/'playback_capabilities.json').read_text())
        cap['installation_id']='server-install';cap['features']=features or []
        if deliveries is not None:cap['deliveries']=deliveries
        responses=[dict(statusCode=200,body=json.dumps(value)) for value in (wire,cap,decision)]
        responses.append(dict(statusCode=200,body='{"outcome":"stopped"}'))
        boundary=re.sub(r'function TaskUniqueId\([^\n]*\n.*?end function\n','',legacy.BOUNDARIES,count=1,flags=re.S)
        boundary=boundary.replace('return {major:"15",minor:"3",revision:"4",build:"2402"}','return {major:"16",minor:"0",revision:"4",build:"834"}')
        boundary=boundary.replace('return "1080p"','return "2160p60"')
        boundary=boundary.replace('return m.uuids.Shift()', 'if m.uuidCounter=invalid then m.uuidCounter=0\n m.uuidCounter++\n return "10000000-0000-4000-8000-"+Right("000000000000"+m.uuidCounter.ToStr(),12)')
        boundary=boundary.replace('(format.codec="aac" and format.passthru=0)','((format.codec="aac" or format.codec="ac3") and format.passthru=0)')
        boundary=boundary.replace('format.chcnt<=2 and format.codec="aac"','format.chcnt<=2 and (format.codec="aac" or format.codec="ac3")')
        for old,new in (device or {}).items():boundary=boundary.replace(old,new)
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td);files=[]
            for name in [*legacy.FILES,ROOT/'components/ApiTask.brs',ROOT/'source/network/Http.brs']:
                text=name.read_text().replace('CreateObject("roDeviceInfo")','FixtureSiloDevice()')
                if name.name=='ApiTask.brs':text=text.replace('function TaskRokuSiloContext(','function UnusedTaskRokuSiloContext(',1)
                if name.name=='Http.brs':text=text.replace('function HttpRequest(','function UnusedHttpRequest(',1)
                file=folder/name.name;file.write_text(text);files.append(file)
            if subtitle_scenario is not None:
                from tests import test_silo_selected_subtitle_fetch as fetch
                helper=folder/'subtitle_fetch.brs';code=fetch.HELPER.read_text()
                for name in ('SiloSubtitleClock','SiloSubtitleUuid','SiloSubtitleFileSystem','SiloSubtitleRead','SiloSubtitleNewPort','SiloSubtitleNewTransfer','SiloSubtitleWait','SiloSubtitleEventType'):
                    code=code.replace('function '+name+'(','function Unused'+name+'(',1)
                helper.write_text(code);files.extend([helper,ROOT/'components/SiloUISubtitleArtifact.brs'])
                sdk=fetch.SDK_BOUNDARIES.replace('function LoadSession(', 'function UnusedSdkLoadSession(',1).replace('function SessionRevision(', 'function UnusedSdkSessionRevision(',1)
                boundary+=sdk
                boundary=boundary.replace('response = m.responses.Shift()', '''response = m.responses.Shift()
    if m.scenario.stockSubtitleSelection=true and request.method="POST" and Instr(1,request.url,"/playback/start")>0
        body=ParseJson(request.body)
        if not body.DoesExist("subtitle_track_id") and not body.DoesExist("subtitle_track_index")
            reply=ParseJson(response.body)
            reply.playback_plan.subtitle={mode:"off",inventory:reply.playback_plan.subtitle.inventory}
            reply.playback_plan.selected_tracks.Delete("subtitle")
            response.body=FormatJson(reply)
        end if
    end if''',1)
            bridge=folder/'SDK.brs';bridge.write_text(boundary+'''
function OrdinaryOriginalJob(session as Object,wire as Object,responses as Object,options as Object,jobChanges as Object) as Object
 m.fixtureSession=session:m.fixtureRevision=0:m.requests=[]:m.timeouts=[]:m.responses=responses:m.changeRevision=false
 m.fixtureFiles={}:m.fixtureDownloads=[]:m.scenario=options.subtitleScenario:options.Delete("subtitleScenario")
 decoded=DecodeSiloResponse("detail",FormatJson(wire),{sourceId:session.sourceId})
 detail=ScopeCatalogData(decoded.data,session.sourceId)
 params={itemId:"fixture-item",fileId:"731",detail:detail,qualityPreference:"original",qualityExplicit:false,
         autoVersion:false,subtitleMode:"off",audioTrackId:"1",audioTrackIndex:1}
 for each key in options
  if options[key]=invalid then params.Delete(key) else params[key]=options[key]
 end for
 m.top={cancelled:false,job:{provider:"silo",action:"playback_start",sourceId:session.sourceId,profileId:session.profileId,generation:7,requestId:41,params:params}}
 for each key in jobChanges
  if jobChanges[key]=invalid then m.top.job.Delete(key) else m.top.job[key]=jobChanges[key]
 end for
 runJob()
 binding=invalid
 if m.scenario<>invalid and m.top.result.ok=true then binding=SiloUISubtitleBinding(m.top.result.plan,7,41)
 return {submittedParams:m.top.job.params,binding:binding,outcome:m.top.result,requests:m.requests,videoQueries:FixtureSiloDevice().videoQueries,audioQueries:FixtureSiloDevice().audioQueries,
         originalFlag:SiloOriginalActivationEnabled(),p8Flag:SiloP8OriginalActivationEnabled(),files:m.fixtureFiles,downloads:m.fixtureDownloads}
end function
''');files.append(bridge)
            opts=dict(options or {})
            if subtitle_scenario is not None:opts['subtitleScenario']=subtitle_scenario
            return run_function(files,'OrdinaryOriginalJob',[session,wire,responses,opts,job or {}],root=folder)

    def test_original_denial_retains_claims_reason_and_dimensions_without_source_identifiers(self):
        def cropped(wire, decision):
            wire['versions'][0]['video_tracks'][0].update(width=3834, height=1602)
        result = self.start(mutate=cropped, options={'qualityExplicit': True})
        attempts = result['outcome']['startAttempts']
        self.assertEqual('qualified_route_not_enabled', attempts[0]['originalReason'])
        self.assertEqual((3834, 1602), (attempts[0]['request']['width'], attempts[0]['request']['height']))
        for private in ('731', 'sess-1', 'http', 'synthetic'):
            self.assertNotIn(private, json.dumps(attempts).replace('httpStatus', 'status'))

    def test_ordinary_original_denial_exposes_subtitle_intent(self):
        for mode in ('auto','forced'):
            with self.subTest(mode=mode):
                result = self.start(options={'subtitleMode': mode, 'qualityExplicit': True})
                self.assertEqual('subtitle_intent', result['outcome']['startAttempts'][0]['originalReason'])

    def body(self,result):
        return json.loads(next(request['body'] for request in result['requests'] if request['method']=='POST'))

    def test_ordinary_explicit_stereo_ac3_p8_preserves_pinned_original_and_owned_guard(self):
        result=self.start();body=self.body(result)
        self.assertEqual(['client_managed_dynamic_range_v1','client_selected_audio_track_v1'],body['client_playback_context']['deliveries']['original_http']['validated_claims'])
        self.assertTrue(result['outcome']['ok'],result['outcome'])
        self.assertEqual(['GET','GET','POST'],[request['method'] for request in result['requests']])
        self.assertFalse(result['originalFlag']);self.assertFalse(result['p8Flag'])
        self.assertEqual(('731','original',False,'file:731:audio:1',1),
                         (body['file_id'],body['quality_preference'],body['allow_alternate_versions'],body['audio_track_id'],body['audio_track_index']))
        self.assertEqual(1,sum(q.get('container')=='mkv' and q.get('codec')=='hevc' and q.get('profile')=='main 10' for q in result['videoQueries']))
        plan=result['outcome']['plan'];descriptor=plan['originalPlayback']
        self.assertNotIn('experimentalOriginal',plan)
        self.assertEqual('p8_explicit_ac3_stereo_v1',descriptor['qualifiedRoute'])
        self.assertEqual(('ac3',2,'stereo',1),(descriptor['audioIdentity']['codec'],descriptor['audioIdentity']['channels'],descriptor['audioIdentity']['layout'],descriptor['audioIdentity']['index']))
        self.assertEqual(7,descriptor['scope']['generation'])
        self.assertEqual('731',plan['versionId'])

    def test_patched_hdr10_copy_keeps_ordinary_p8_on_negotiated_hls(self):
        def hdr10_copy(wire,decision):
            raw=decision['playback_plan']
            raw.update(delivery='server_remux_hls',decision_reason='server_remux')
            raw['stream'].update(protocol='hls',container='hls',url='/api/v2/playback/transcode/fixture/master.m3u8?st=synthetic')
            raw['effective_recipe'].update(video_codec='hevc',audio_codec='ac3',video_sample_entry='hvc1',dynamic_range='hdr10')
            raw['transformations']=[dict(name='hls_separate_audio',executor='server',recipe_version='1')]
        result=self.start(mutate=hdr10_copy,features=['native_hls_separate_audio_v1'],device={'DolbyVision:true':'DolbyVision:false'})
        body=self.body(result)
        self.assertEqual([],body['client_playback_context']['deliveries']['original_http']['validated_claims'])
        self.assertEqual(('731','file:731:audio:1',1,False),
                         (body['file_id'],body['audio_track_id'],body['audio_track_index'],body['allow_alternate_versions']))
        self.assertEqual([],body['client_playback_context']['deliveries']['hls']['hdr_details']['dolby_vision_profiles'])
        self.assertTrue(body['client_playback_context']['deliveries']['hls']['hdr_details']['hdr10'])
        self.assertTrue(result['outcome']['ok'],result['outcome'])
        starts=[json.loads(request['body']) for request in result['requests'] if request['method']=='POST']
        self.assertTrue(starts)
        for start in starts:
            self.assertEqual([],start['client_playback_context']['deliveries']['original_http']['validated_claims'])
        self.assertEqual('hls',result['outcome']['plan']['streamFormat'])
        self.assertEqual('731',result['outcome']['plan']['versionId'])
        self.assertNotIn('originalPlayback',result['outcome']['plan'])

    def test_legacy_h264_hls_does_not_suppress_ordinary_p8_promotion(self):
        result=self.start(features=['native_hls_playback_v1'],deliveries=['original_http','server_transcode_hls'])
        body=self.body(result)
        self.assertEqual(['client_managed_dynamic_range_v1','client_selected_audio_track_v1'],body['client_playback_context']['deliveries']['original_http']['validated_claims'])
        hls=body['client_playback_context']['deliveries']['hls']
        self.assertTrue(hls['enabled'])
        self.assertEqual(['h264'],hls['video_codecs'])
        self.assertEqual(['native_hls_playback_v1'],hls['features'])
        self.assertTrue(result['outcome']['ok'],result['outcome'])
        self.assertEqual('p8_explicit_ac3_stereo_v1',result['outcome']['plan']['originalPlayback']['qualifiedRoute'])

    def test_ordinary_h264_without_explicit_audio_skips_original_decoder_queries(self):
        def h264(wire,decision):
            file=wire['versions'][0]
            file.update(codec_audio='aac',audio_tracks=[dict(codec='aac',channels=2,layout='stereo',default=True)],codec_video='h264',hdr=False,resolution='1080p',video_tracks=[dict(codec='h264',profile='high',level=40,width=1920,height=1080,bit_depth=8,frame_rate='24000/1001',interlaced=False)])
            raw=decision['playback_plan']
            raw['decision_reason']='direct_play'
            for section in ('source','effective_recipe'):
                raw[section]=dict(media_file_id='731',container='mkv',video_codec='h264',video_profile='high',video_level=40,width=1920,height=1080,bit_depth=8,dynamic_range='sdr',audio_codec='aac',audio_channels=2,audio_layout='stereo')
            raw['selected_tracks']['audio']={'id':'file:731:audio:0','index':0}
        result=self.start(mutate=h264,options={'audioTrackId':None,'audioTrackIndex':None})
        queries=[q for q in result['videoQueries'] if q.get('container')=='mkv' and q.get('codec')=='hevc' and q.get('profile')=='main 10']
        self.assertEqual(0,len(queries),queries)
        self.assertEqual([],self.body(result)['client_playback_context']['deliveries']['original_http']['validated_claims'])
        self.assertTrue(any(q['method']=='POST' for q in result['requests']))
        self.assertTrue(result['outcome']['ok'],result['outcome'])

    def test_missing_or_mismatched_actual_job_scope_cannot_promote_ordinary(self):
        for scope in ({'generation':None},{'generation':True},{'sourceId':'silo:different'},{'profileId':'other'}):
            with self.subTest(scope=scope):
                result=self.start(job=scope)
                self.assertNotIn('originalPlayback',result['outcome'].get('plan',{}))
                for request in result['requests']:
                    if request['method']=='POST':
                        self.assertEqual([],json.loads(request['body'])['client_playback_context']['deliveries']['original_http']['validated_claims'])

    def test_unqualified_hardware_os_output_and_decoder_keep_ordinary_claims_absent(self):
        for old,new in [('return "C000X"','return "4802X"'),('build:"834"','build:"835"'),('return "2160p60"','return "1080p"'),('return {result:true}','return {result:false}')]:
            with self.subTest(old=old):
                result=self.start(device={old:new})
                self.assertNotIn('originalPlayback',result['outcome'].get('plan',{}))
                for request in result['requests']:
                    if request['method']=='POST':self.assertEqual([],json.loads(request['body'])['client_playback_context']['deliveries']['original_http']['validated_claims'])

    def test_ordinary_route_requires_explicit_stereo_ac3_and_exact_p8_base(self):
        def changed_audio(wire,decision):
            wire['versions'][0]['audio_tracks'][1].update(channels=6,layout='5.1')
        def p7(wire,decision):wire['versions'][0]['video_tracks'][0]['dv_profile']=7
        def p5(wire,decision):wire['versions'][0]['video_tracks'][0]['dv_profile']=5
        def missing_base(wire,decision):wire['versions'][0]['video_tracks'][0].pop('dv_bl_present')
        for mutation,options in [(changed_audio,None),(p7,None),(p5,None),(missing_base,None),(None,{'audioTrackId':None,'audioTrackIndex':None}),(None,{'subtitleMode':'auto'}),(None,{'qualityPreference':'1080p'}),(None,{'bandwidthCapKbps':1000}),(None,{'speculativePrebuffer':True}),(None,{'originalDisabled':True})]:
            with self.subTest(mutation=mutation,options=options):
                result=self.start(mutate=mutation,options=options)
                self.assertNotIn('originalPlayback',result['outcome'].get('plan',{}))
                for request in result['requests']:
                    if request['method']=='POST':self.assertEqual([],json.loads(request['body'])['client_playback_context']['deliveries']['original_http']['validated_claims'])

    def test_ordinary_source_class_does_not_expand_to_1080_or_sixty_fps(self):
        def hd(wire,decision):
            wire['versions'][0]['video_tracks'][0].update(width=1920,height=1080)
            for section in ('source','effective_recipe'):decision['playback_plan'][section].update(width=1920,height=1080)
        def sixty(wire,decision):
            wire['versions'][0]['video_tracks'][0]['frame_rate']='60'
            for section in ('source','effective_recipe'):decision['playback_plan'][section]['frame_rate']=60
        for mutation in (hd,sixty):
            with self.subTest(mutation=mutation):
                result=self.start(mutate=mutation)
                self.assertEqual([],self.body(result)['client_playback_context']['deliveries']['original_http']['validated_claims'])
                self.assertNotIn('originalPlayback',result['outcome'].get('plan',{}))
