import json
from pathlib import Path
import tempfile
import unittest
from tools.brightscript import run_function
from tests import test_silo_playback_task as playback
ROOT = Path(__file__).resolve().parents[1]
FILES = [ROOT/'source/adapters/SiloAdapter.brs', ROOT/'source/core/SiloPlaybackPolicy.brs', ROOT/'components/TaskSiloReplan.brs', ROOT/'source/core/SiloUIDetailPolicy.brs']

class SiloNativeVersionsTests(unittest.TestCase):
    def call(self, name, *args):
        with tempfile.TemporaryDirectory() as root:
            return run_function(FILES, name, list(args), root=Path(root))

    def detail(self):
        return {'item':{'sourceId':'silo:test','itemId':'item'},'versionsComplete':True,
                'versions':[{'sourceId':'silo:test','itemId':'item','versionId':x,'durationMs':100000,'bitrateKbps':20000} for x in ['first','best','foreign-edition']],
                'playbackVariants':[{'variantId':'theatrical','partCount':1,'parts':[{'partIndex':1,'defaultFileId':'best','fileIds':['first','best']}]}]}

    def test_detail_keeps_4k_dv_and_hdr_files_before_playback_negotiation(self):
        raw=json.loads((ROOT/'tests/fixtures/silo/catalog_item_detail_movie.json').read_text())
        template=raw['versions'][0]
        raw['versions']=[]
        for name,profile,compat in [('sdr',0,0),('hdr10',0,0),('dv5',5,0),
                                    ('dv7',7,6),('dv81',8,1),('dv82',8,2),('dv84',8,4)]:
            version={**template,'file_id':name,'resolution':'2160p','codec_video':'hevc',
                     'hdr':name!='sdr','video_tracks':[{'codec':'hevc','width':3840,'height':2160,
                        'dv_profile':profile,'dv_bl_compat_id':compat,'dv_config_present':profile>0,
                        'dv_bl_compat_id_present':profile>0,'interlaced':False}]}
            raw['versions'].append(version)
        result=self.call('DecodeSiloResponse','detail',json.dumps(raw),{'sourceId':'silo:test'})
        self.assertTrue(result['ok'])
        self.assertEqual(['sdr','hdr10','dv5','dv7','dv81','dv82','dv84'],
                         [v['versionId'] for v in result['data']['versions']])
        self.assertTrue(all(v['resolution']=='2160p' for v in result['data']['versions']))
        self.assertTrue(result['data']['versionsComplete'])

    def test_empty_detail_inventory_stays_distinct_from_playback_capability_failure(self):
        raw=json.loads((ROOT/'tests/fixtures/silo/catalog_item_detail_movie.json').read_text())
        raw['versions']=[]
        result=self.call('DecodeSiloResponse','detail',json.dumps(raw),{'sourceId':'silo:test'})
        self.assertTrue(result['ok'])
        self.assertEqual([],result['data']['versions'])
        self.assertTrue(result['data']['versionsComplete'])

    def test_native_default_anchor_and_same_part_inventory(self):
        self.assertEqual(self.call('SiloNativeSelection',self.detail(),'silo:test','item',''),{'fileId':'best','allowedFileIds':['first','best'],'allowAlternateVersions':True})
        self.assertEqual(self.call('SiloNativeSelection',self.detail(),'silo:test','item','first'),{'fileId':'first','allowedFileIds':['first'],'allowAlternateVersions':False})

    def test_ambiguous_or_invalid_native_groups_are_pinned(self):
        detail=self.detail();detail['playbackVariants'][0]['parts'][0]['defaultFileId']='missing'
        self.assertEqual(self.call('SiloNativeSelection',detail,'silo:test','item','')['allowAlternateVersions'],False)
        detail=self.detail();detail['playbackVariants'][0]['partCount']=2
        self.assertFalse(self.call('SiloNativeSelection',detail,'silo:test','item','')['allowAlternateVersions'])

    def test_effective_identity_only_accepts_trusted_auto_inventory(self):
        decision={'playback_plan':{'requested_media_file_id':'first','effective_media_file_id':'best','source':{'media_file_id':'best'}}}
        self.assertTrue(self.call('TaskSiloDecisionIdentity',decision,'first','',['first','best']))
        self.assertFalse(self.call('TaskSiloDecisionIdentity',decision,'first'))
        self.assertFalse(self.call('TaskSiloDecisionIdentity',decision,'first','',['first','foreign-edition']))
        decision['playback_plan']['source']['media_file_id']='first'
        self.assertFalse(self.call('TaskSiloDecisionIdentity',decision,'first','',['first','best']))

    def test_adapter_retains_native_group_defaults_and_file_inventory(self):
        raw=json.loads((ROOT/'tests/fixtures/silo/catalog_item_detail_movie.json').read_text())
        ids=[v['file_id'] for v in raw['versions']]
        raw['playback_variants']=[{'variant_id':'native','part_count':1,'default_file_id':ids[-1],'presentation_group_key':'cut','presentation_kind':'movie','edition_key':'theatrical','parts':[{'part_index':1,'default_file_id':ids[-1],'versions':raw['versions']}]}]
        result=self.call('DecodeSiloResponse','detail',json.dumps(raw),{'sourceId':'silo:test'})
        self.assertEqual(result['data']['playbackVariants'][0]['parts'][0]['fileIds'],ids)
        self.assertEqual(result['data']['playbackVariants'][0]['parts'][0]['defaultFileId'],ids[-1])

    def test_start_auto_flag_is_explicit_and_manual_default_remains_pinned(self):
        params=json.loads((ROOT/'tests/fixtures/silo/roku_start_input.json').read_text())
        self.assertFalse(self.call('SiloStartBody',{},params)['body']['allow_alternate_versions'])
        params['allowAlternateVersions']=True
        self.assertTrue(self.call('SiloStartBody',{},params)['body']['allow_alternate_versions'])

    def test_single_part_uses_variant_default_when_part_default_absent(self):
        detail=self.detail();variant=detail['playbackVariants'][0]
        variant['defaultFileId']='best';del variant['parts'][0]['defaultFileId']
        self.assertEqual(self.call('SiloNativeSelection',detail,'silo:test','item','')['fileId'],'best')

    def test_video_tracks_retain_bounded_signal_facts_without_file_strings(self):
        raw=json.loads((ROOT/'tests/fixtures/silo/catalog_item_detail_movie.json').read_text())
        raw['versions'][0]['video_tracks']=[{'codec':'hevc','profile':'Main 10','level':153,'width':3840,'height':2160,'bit_depth':10,'frame_rate':'24000/1001','color_transfer':'smpte2084','dv_profile':8,'dv_bl_compat_id':1,'dv_config_present':True,'dv_bl_compat_id_present':True,'interlaced':False,'title':'private title','file_path':'private path','frame_rate_extra':'private'}]
        version=self.call('DecodeSiloResponse','detail',json.dumps(raw),{})['data']['versions'][0]
        self.assertEqual(version['videoTracks'][0],{k:v for k,v in raw['versions'][0]['video_tracks'][0].items() if k not in ['title','file_path','frame_rate_extra']})

    def test_required_requested_identity_cannot_be_omitted(self):
        decision={'playback_plan':{'effective_media_file_id':'first','source':{'media_file_id':'first'}}}
        self.assertFalse(self.call('TaskSiloDecisionIdentity',decision,'first'))
        decision['playback_plan']['requested_media_file_id']='first'
        self.assertTrue(self.call('TaskSiloDecisionIdentity',decision,'first'))


    def capped_native_start(self, cap, *, manual=False, bitrates=(30000, 70000)):
        class CaptureScenario(playback.SiloPlaybackTaskTests):
            def worker(self, function, arguments, **kwargs):
                if function == 'RunSiloNativeBestStart':
                    return arguments
                return super().worker(function, arguments, **kwargs)
        harness = playback.SiloPlaybackTaskTests()
        arguments = CaptureScenario().native_best_start(equal=True)
        session, params, responses = arguments[:3]
        raw = json.loads(responses[0]['body'])
        for version, bitrate in zip(raw['versions'], bitrates):
            version['bitrate'] = bitrate
        raw['playback_variants'][0]['parts'][0]['versions'] = raw['versions']
        responses[0]['body'] = json.dumps(raw)
        params['detail'] = harness.worker('DecodeSiloResponse',
            ['detail', json.dumps(raw), {'sourceId':session['sourceId']}])['data']
        params['detail']['item']['sourceId'] = session['sourceId']
        params.update(bandwidthCapKbps=cap, autoVersion=not manual,
                      fileId='f2' if manual else 'f1')
        if cap == 0:
            del params['bandwidthCapKbps']
        return harness.worker('RunSiloNativeBestStart', arguments)

    def test_auto_prefers_same_part_file_within_bandwidth_cap(self):
        result = self.capped_native_start(40000)
        self.assertTrue(result['outcome']['ok'], result)
        posted = [json.loads(r['body']) for r in result['requests'] if r['method'] == 'POST']
        self.assertEqual('f1', posted[0]['file_id'])
        self.assertEqual(40000, posted[0]['bandwidth_cap_kbps'])
        self.assertFalse(posted[0]['allow_alternate_versions'])

    def test_unlimited_auto_still_selects_higher_bitrate(self):
        result = self.capped_native_start(0)
        self.assertTrue(result['outcome']['ok'], result)
        posted = [json.loads(r['body']) for r in result['requests'] if r['method'] == 'POST']
        self.assertEqual('f2', posted[0]['file_id'])
        self.assertNotIn('bandwidth_cap_kbps', posted[0])

    def test_capped_manual_selection_remains_pinned(self):
        result = self.capped_native_start(40000, manual=True)
        self.assertTrue(result['outcome']['ok'], result)
        posted = [json.loads(r['body']) for r in result['requests'] if r['method'] == 'POST']
        self.assertEqual('f2', posted[0]['file_id'])
        self.assertEqual(40000, posted[0]['bandwidth_cap_kbps'])
        self.assertFalse(posted[0]['allow_alternate_versions'])

    def test_no_file_within_cap_keeps_default_for_server_adaptation(self):
        result = self.capped_native_start(20000)
        self.assertTrue(result['outcome']['ok'], result)
        posted = [json.loads(r['body']) for r in result['requests'] if r['method'] == 'POST']
        self.assertEqual('f1', posted[0]['file_id'])
        self.assertEqual(20000, posted[0]['bandwidth_cap_kbps'])
        self.assertFalse(posted[0]['allow_alternate_versions'])

    def native_p7_start(self, auto_version):
        # Synthetic same-file inventory: Auto has no different edition to choose.
        # Execute the real worker through its existing HTTP/device boundary.
        harness = playback.SiloPlaybackTaskTests()
        raw = json.loads((ROOT/'tests/fixtures/silo/catalog_item_detail_movie.json').read_text())
        raw['content_id'] = 'fixture-item'
        version = raw['versions'][0]
        version.update(file_id='p7', resolution='2160p', codec_video='hevc',
                       codec_audio='eac3', hdr=True, bitrate=40000,
                       audio_tracks=[{'index':0,'codec':'eac3','channels':6,'default':True,'language':'eng'}],
                       video_tracks=[{'codec':'hevc','profile':'Main 10','level':153,
                                      'width':3840,'height':2160,'bit_depth':10,
                                      'frame_rate':'24000/1001','color_transfer':'smpte2084',
                                      'dv_profile':7,'dv_el_present':True,'dv_config_present':True,
                                      'dv_bl_compat_id':6,'dv_bl_compat_id_present':True,
                                      'video_range':'dolbyvision','interlaced':False}])
        raw['versions'] = [version]
        raw['playback_variants'] = [{'variant_id':'native','part_count':1,
            'parts':[{'part_index':1,'default_file_id':'p7','versions':[version]}]}]
        detail = harness.worker('DecodeSiloResponse', ['detail',json.dumps(raw),
                                {'sourceId':harness.session()['sourceId']}])['data']
        detail['item']['sourceId'] = harness.session()['sourceId']
        capability = json.loads((ROOT/'tests/fixtures/silo/playback_capabilities.json').read_text())
        capability['features'] = ['native_hls_separate_audio_v1','server_dv7_to_dv81_v1']
        terminal = {'protocol_version':3,'server_features':capability['features'],
                    'outcome':'adaptation_unavailable',
                    'terminal':{'reason':'adaptation_exhausted','message':'No supported route.','retryable':False}}
        responses = [{'statusCode':200,'body':json.dumps(value)} for value in [raw,capability,terminal]]
        params = {'itemId':'fixture-item','fileId':'p7','detail':detail,
                  'autoVersion':auto_version,'qualityPreference':'original','qualityExplicit':True}
        return harness.worker('RunSiloNativeBestStart', [harness.session(),params,responses])

    def test_auto_and_manual_same_p7_original_negotiate_identical_native_request_and_error(self):
        auto = self.native_p7_start(True)
        manual = self.native_p7_start(False)
        for result in [auto, manual]:
            self.assertEqual(['GET','GET','POST'], [r['method'] for r in result['requests']])
            self.assertFalse(result['outcome']['ok'])
            self.assertEqual('adaptation_exhausted', result['outcome'].get('reason'))
        auto_body = json.loads(auto['requests'][-1]['body'])
        manual_body = json.loads(manual['requests'][-1]['body'])
        self.assertEqual('p7', auto_body['file_id'])
        self.assertEqual('original', auto_body['quality_preference'])
        self.assertFalse(auto_body['allow_alternate_versions'])
        self.assertIn('server_dv7_to_dv81_v1',
                      auto_body['client_playback_context']['deliveries']['hls']['features'])
        # Neither selection adds a user audio override; the same default EAC3
        # track and output evidence feed both capability/context projections.
        for key in ['audio_track_id','audio_track_index']:
            self.assertNotIn(key, auto_body)
            self.assertNotIn(key, manual_body)
        for key in ['client_features','client_capabilities','client_playback_context']:
            self.assertEqual(auto_body[key], manual_body[key], key)
        self.assertEqual(auto_body, manual_body)
        checks = playback.SiloPlaybackTaskTests()
        for result, selection in [(auto, 'auto'), (manual, 'manual')]:
            checks.assert_safe_start_response_facts(result)
            self.assertEqual(selection, result['outcome']['startRequestFacts']['selection'])
            for attempt in result['outcome']['startAttempts']:
                self.assertEqual(selection, attempt['request']['selection'])
        for result in (auto, manual):
            result['outcome']['startRequestFacts'].pop('selection')
            for attempt in result['outcome']['startAttempts']:
                attempt['request'].pop('selection')
        self.assertEqual(auto['outcome'], manual['outcome'])
