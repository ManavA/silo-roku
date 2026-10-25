"""Official omitted-false signal through public detail decoding and actual runJob.

Reference: official 48ae561d models/media.go DVELPresent bool omitempty.
Only the registry/device/HTTP boundary is emulated. Negotiation, ranking,
request construction, response admission and worker callbacks remain actual.
"""
import copy
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET
from tools.brightscript import run_function
from tests import test_silo_playback_task as playback

ROOT=Path(__file__).resolve().parents[1]
OMITTED=object()


class SiloHdrSignalTests(unittest.TestCase):
    def worker(self, el=OMITTED, *, edits=None, features=True, profile=8, unqualified_firmware=False, signal='dv'):
        wire=json.loads((playback.FIXTURES/'catalog_item_detail_movie.json').read_text())
        first=copy.deepcopy(wire['versions'][0])
        first.update(file_id='f1',resolution='1080p',codec_video='h264',hdr=False,bitrate=12000,
            video_tracks=[dict(codec='h264',profile='high',level=40,width=1920,height=1080,
                               bit_depth=8,frame_rate='24000/1001',interlaced=False)])
        second=copy.deepcopy(first)
        video=dict(codec='hevc',profile='Main 10',level=153,width=3840,height=2160,
            bit_depth=10,frame_rate='24000/1001',interlaced=False,color_transfer='smpte2084',
            dv_profile=profile,dv_level=6,dv_bl_compat_id=1,dv_config_present=True,
            dv_bl_compat_id_present=True,dv_bl_present=True,dv_rpu_present=True,dv_enhancement_layer='none')
        if el is not OMITTED:video['dv_el_present']=el
        if signal != 'dv':
            video={key:value for key,value in video.items() if not key.startswith('dv_')}
            video['color_transfer']='smpte2084' if signal=='hdr10' else 'bt709'
        for key,value in (edits or {}).items():
            if value is OMITTED:video.pop(key,None)
            else:video[key]=value
        second.update(file_id='f2',resolution='2160p',codec_video='hevc',hdr=signal!='sdr',bitrate=40000,video_tracks=[video])
        wire['versions']=[first,second]
        wire['playback_variants']=[dict(variant_id='native',part_count=1,parts=[dict(part_index=0,default_file_id='f1',versions=[first,second])])]
        caps=json.loads((playback.FIXTURES/'playback_capabilities.json').read_text())
        caps['features']=['native_hls_separate_audio_v1'] if features else []
        low=json.loads((playback.FIXTURES/'playback_decision_plan.json').read_text())
        low['playback_plan']['selected_tracks']={'audio':dict(id='file:f1:audio:0',index=0)}
        low['playback_plan']['source'].update(video_codec='h264',width=1920,height=1080)
        high=copy.deepcopy(low)
        plan=high['playback_plan']
        plan.update(requested_media_file_id='f2',effective_media_file_id='f2',delivery='server_remux_hls',
            effective_recipe=dict(video_codec='hevc',audio_codec='eac3',audio_channels=6,dynamic_range='dolby_vision',video_sample_entry='dvh1'),
            transformations=[dict(name='hls_separate_audio',executor='server',recipe_version='1')])
        plan['source'].update(media_file_id='f2',video_codec='hevc',width=3840,height=2160,
            dolby_vision_profile=profile,dolby_vision_level=6,dv_bl_compat_id=video.get('dv_bl_compat_id',1))
        if signal != 'dv':plan['effective_recipe'].update(dynamic_range=signal,video_sample_entry='hvc1')
        plan['stream'].update(protocol='hls',container='hls')
        plan['selected_tracks']={'audio':dict(id='file:f2:audio:0',index=0)}
        session=playback.SiloPlaybackTaskTests().session()
        os=dict(major='16',minor='0',revision='4',build='99999') if unqualified_firmware else dict(major='15',minor='3',revision='4',build='2402')
        config=dict(wire=wire,caps=caps,low=low,high=high,session=session,os=os)
        # Reuse only the SDK device factory, not legacy policy wrappers.
        start=playback.BOUNDARIES.index('function FixtureSiloDevice()')
        stop=playback.BOUNDARIES.index('\nfunction RunSiloCapabilities',start)
        device=playback.BOUNDARIES[start:stop].replace('return "1080p"','return "2160p60"')
        device=device.replace('return {major:"15",minor:"3",revision:"4",build:"2402"}', 'return GetGlobalAA().hdrConfig.os')
        device=device.replace('return m.uuids.Shift()', '''if m.sequence=invalid then m.sequence=0
        m.sequence++
        return "10000000-0000-4000-8000-"+Right("000000000000"+m.sequence.ToStr(),12)''')
        boundary=device+'''
' SDK serializer workaround: brs mistakes shared references for cycles.
function FixtureFormatJson(value as Dynamic) as String
 return FormatJson(FixtureJsonCopy(value))
end function
function FixtureJsonCopy(value as Dynamic) as Dynamic
 if type(value)="roAssociativeArray"
 out={}:for each key in value:out[key]=FixtureJsonCopy(value[key]):end for:return out
 else if type(value)="roArray"
 out=[]:for each child in value:out.Push(FixtureJsonCopy(child)):end for:return out
 end if
 return value
end function

function FixtureRegistrySection(name as String) as Object
 return {Exists:function(key as String) as Boolean
 return key="session" or key="revision"
 end function,Read:function(key as String) as String
 if key="revision" then return "0"
 return FormatJson(GetGlobalAA().hdrConfig.session)
 end function}
end function
function HttpRequest(request as Object,timeoutMs=0 as Integer) as Object
 m.requests.Push(request)
 if request.method="GET" and Instr(1,request.url,"/playback/capabilities")>0 then return HttpResponse(request,200,FormatJson(m.config.caps))
 if request.method="GET" then return HttpResponse(request,200,FormatJson(m.config.wire))
 if request.method="POST" and Instr(1,request.url,"/playback/start")>0
 body=ParseJson(request.body)
 if body.file_id="f2" then raw=m.config.high else raw=m.config.low
 return HttpResponse(request,200,FormatJson(raw))
 end if
 return HttpResponse(request,200,"{""outcome"":""stopped""}")
end function
function RunHdrSignal(config as Object) as Object
 GetGlobalAA().hdrConfig=config:m.config=config:m.requests=[]
 decoded=DecodeSiloResponse("detail",FormatJson(config.wire),{sourceId:config.session.sourceId})
 detail=ScopeCatalogData(decoded.data,config.session.sourceId)
 m.top={cancelled:false,job:{provider:"silo",action:"playback_start",sourceId:config.session.sourceId,profileId:config.session.profileId,generation:7,requestId:67,params:{itemId:detail.item.itemId,fileId:"f1",detail:detail,autoVersion:true,qualityPreference:"original",qualityExplicit:false,subtitleMode:"off"}}}
 runJob()
 return {outcome:m.top.result,requests:m.requests,video:detail.versions[1].videoTracks[0]}
end function
'''
        with tempfile.TemporaryDirectory(prefix='silo-hdr-signal-067-') as directory:
            folder=Path(directory);files=[]
            for node in ET.parse(ROOT/'components/ApiTask.xml').getroot().findall('script'):
                name=node.attrib['uri'].removeprefix('pkg:/');source=(ROOT/name).read_text()
                source=source.replace('FormatJson(', 'FixtureFormatJson(')
                source=source.replace('CreateObject("roDeviceInfo")','FixtureSiloDevice()')
                source=source.replace('AppRegistrySection(provider)','FixtureRegistrySection(provider)')
                if name=='source/network/Http.brs':source=source.replace('function HttpRequest(', 'function UnusedSdkHttpRequest(',1)
                path=folder/Path(name).name;path.write_text(source);files.append(path)
            path=folder/'Boundary.brs';path.write_text(boundary);files.append(path)
            return run_function(files,'RunHdrSignal',[config],root=folder)

    def test_official_omitted_false_p8_ranks_qualified_4k_before_1080_in_actual_job(self):
        result=self.worker()
        starts=[json.loads(r['body']) for r in result['requests'] if r['method']=='POST' and '/playback/start' in r['url']]
        self.assertEqual('f2',starts[0]['file_id'],result)
        self.assertTrue(result['outcome']['ok'],result)
        self.assertEqual('f2',result['outcome']['plan']['versionId'])
        self.assertEqual('original',starts[0]['quality_preference'])
        self.assertIs(type(starts[0]['protocol_version']),int)
        self.assertEqual(3,starts[0]['protocol_version'])
        self.assertFalse(starts[0]['allow_alternate_versions'])
        self.assertEqual(['native_hls_separate_audio_v1'],starts[0]['client_features'])
        selected=result['outcome']['plan']['siloPlayback']['selectedTracks']['audio']
        self.assertEqual(dict(id='file:f2:audio:0',index=0),selected)
        self.assertIs(type(selected['index']),int)
        accepted=result['outcome']['data']['playbackDetail']['versions'][1]
        self.assertEqual(('f2',3840,2160),(accepted['versionId'],accepted['videoTracks'][0]['width'],accepted['videoTracks'][0]['height']))

    def test_present_false_is_equivalent_but_true_or_malformed_el_cannot_upgrade(self):
        for el,expected in [(False,'f2'),(True,'f1'),('false','f1'),(None,'f1'),(0,'f1'),({},'f1'),([],'f1')]:
            with self.subTest(el=el):
                result=self.worker(el)
                self.assertTrue(result['outcome']['ok'],result['outcome'])
                start=next(json.loads(r['body']) for r in result['requests'] if r['method']=='POST')
                self.assertEqual(expected,start['file_id'])
                self.assertEqual(expected,result['outcome']['plan']['versionId'])
                if el is not False and el is not True:self.assertNotIn('dv_el_present',result['video'])

    def test_missing_positive_facts_or_contradictory_layer_do_not_gain_false_el(self):
        cases=[{key:OMITTED} for key in ('dv_config_present','dv_bl_compat_id_present','dv_bl_present','dv_rpu_present','dv_enhancement_layer')]
        cases += [dict(dv_bl_present='true'),dict(dv_bl_compat_id=2),dict(dv_enhancement_layer='FEL'),dict(dv_enhancement_layer=True)]
        for edits in cases:
            with self.subTest(edits=edits):
                result=self.worker(edits=edits)
                self.assertTrue(result['outcome']['ok'],result['outcome'])
                self.assertEqual('f1',result['outcome']['plan']['versionId'])
                self.assertNotIn('dv_el_present',result['video'])

    def test_normalization_does_not_enable_unpatched_or_other_firmware_p8_claims(self):
        for options in (dict(features=False),dict(unqualified_firmware=True)):
            with self.subTest(options=options):
                result=self.worker(**options)
                self.assertTrue(result['outcome']['ok'],result['outcome'])
                self.assertEqual('f1',result['outcome']['plan']['versionId'])
                start=next(json.loads(r['body']) for r in result['requests'] if r['method']=='POST')
                self.assertNotIn(8,start['client_capabilities']['hdr_details']['dolby_vision_profiles'])

    def test_plain_hdr10_and_sdr_still_select_the_actual_4k_file(self):
        for signal in ('hdr10','sdr'):
            with self.subTest(signal=signal):
                result=self.worker(signal=signal)
                self.assertTrue(result['outcome']['ok'],result['outcome'])
                self.assertEqual('f2',result['outcome']['plan']['versionId'])
                self.assertNotIn('dv_el_present',result['video'])

    def test_complete_p5_omitted_and_explicit_false_keep_native_priority(self):
        for el in (OMITTED, False):
            with self.subTest(el=el):
                result=self.worker(el,profile=5,edits=dict(dv_bl_compat_id=0))
                self.assertTrue(result['outcome']['ok'],result['outcome'])
                self.assertEqual('f2',result['outcome']['plan']['versionId'])
                self.assertIs(False,result['video']['dv_el_present'])

if __name__=='__main__':unittest.main()
