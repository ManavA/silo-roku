"""Synthetic SDK identities at the runJob/HTTP seam; no hardware qualification."""
import json
import unittest
from tests import test_silo_compat_continuation as continuation
from tests import test_silo_level50_hdr10 as hdr10
from tests import test_silo_delivery_capabilities as delivery

STB = {'return "C000X"': 'return "4850X"', 'return "TV"': 'return "STB"',
       'ModelNumber:"C208X"': 'ModelNumber:"4850X"'}
DV_STB = dict(STB, **{'DolbyVision:true':'DolbyVision:true'})
AAC_ONLY = {
    'if format.chcnt = invalid then return {result:(format.codec="aac" and format.passthru=0) or (format.codec="eac3" and format.passthru=1)}':
    'if format.chcnt = invalid then return {result:format.codec="aac" and format.passthru=0}',
    'if format.passthru = 1 then return {result:format.codec="eac3" and format.chcnt<=6}':
    'if format.passthru = 1 then return {result:false}',
}


def starts(result):
    return [json.loads(r['body']) for r in result['requests'] if '/playback/start' in r['url']]


class CrossProfileNegotiation(unittest.TestCase):
    def test_stb_p5_priority_requires_copy_negotiation_and_typed_dv_output(self):
        def fixture(wire, decision):
            version = wire['versions'][0]
            version.update(container='mp4', codec_audio='aac', audio_tracks=[dict(codec='aac', language='en', channels=2, layout='stereo', default=True)])
            version['video_tracks'][0].update(dv_profile=5, dv_level=6, dv_config_present=True,
                dv_bl_compat_id_present=True, dv_bl_compat_id=0, dv_bl_present=True,
                dv_rpu_present=True, dv_el_present=False, dv_enhancement_layer='none')
            wire['playback_variants'][0]['default_file_id']='732'
            wire['playback_variants'][0]['parts'][0]['default_file_id']='732'
        for features, display, expected in [(['native_hls_separate_audio_v1'], 'true', '731'),
                                          ([], 'true', '732'),
                                          (['native_hls_separate_audio_v1'], 'false', '732'),
                                          (['native_hls_separate_audio_v1'], '"true"', '732')]:
            with self.subTest(features=features, display=display):
                device = dict(STB, **AAC_ONLY)
                device['DolbyVision:true'] = 'DolbyVision:'+display
                result = continuation.CompatContinuation().job(enabled=False, p7_enabled=False,
                    automatic_hdr10=False, features=features, options={'fileId':'732'}, mutate=fixture, device=device)
                bodies=starts(result)
                self.assertEqual([expected], [b['file_id'] for b in bodies], result['outcome'])
                hls=bodies[0]['client_playback_context']['deliveries']['hls']
                self.assertEqual(['aac'] if features else [], hls['audio_decode_codecs'])
                self.assertEqual([], hls['audio_passthrough_codecs'])
                self.assertNotIn(8, hls.get('hdr_details', {}).get('dolby_vision_profiles', []))
                if expected=='731':
                    self.assertIn(5, hls['hdr_details']['dolby_vision_profiles'])
                    # Source priority is not acceptance: this unrelated fixture receipt must refuse.
                    self.assertFalse(result['outcome']['ok'])
                    self.assertNotIn('plan', result['outcome'])

    def test_hdr10_only_4k_stb_selects_independently_of_dv(self):
        for features in (['native_hls_separate_audio_v1'], []):
            with self.subTest(features=features):
                sdk=dict(STB)
                sdk['DolbyVision:true']='DolbyVision:false'
                result=hdr10.Level50HDR10().start(sdk=sdk, features=features)
                bodies=starts(result)
                self.assertEqual(['731'], [b['file_id'] for b in bodies], result['outcome'])
                hls=bodies[0]['client_playback_context']['deliveries']['hls']
                self.assertNotIn(8, hls.get('hdr_details', {}).get('dolby_vision_profiles', []))
                if features:
                    self.assertTrue(hls['hdr_details']['hdr10'])
                    self.assertEqual(['aac'], hls['audio_decode_codecs'])
                    self.assertTrue(result['outcome']['ok'], result['outcome'])
                    self.assertEqual('hls', result['outcome']['plan']['streamFormat'])
                else:
                    self.assertFalse(hls['enabled'])
                    self.assertFalse(result['outcome']['ok'])
                    self.assertNotIn('plan', result['outcome'])

    def test_legacy_sdr_h264_aac_route_needs_no_dv_or_surround_claim(self):
        for features in ([], ['native_hls_separate_audio_v1']):
            with self.subTest(features=features):
                result=delivery.IndependentDeliveryCapabilities().start(audio='mp4_and_ts', features=features)
                body=starts(result)[0]
                self.assertEqual('732', body['file_id'])
                hls=body['client_playback_context']['deliveries']['hls']
                self.assertEqual(['h264'], hls['video_codecs'])
                self.assertEqual(['aac'], hls['audio_decode_codecs'])
                self.assertEqual([], hls['audio_passthrough_codecs'])
                self.assertNotIn('hdr_details', hls)
                self.assertTrue(result['outcome']['ok'], result['outcome'])
                self.assertEqual('hls', result['outcome']['plan']['streamFormat'])

    def test_stb_accepts_p5_only_with_matching_copied_dv_receipt(self):
        from tests import test_silo_native_hdr10 as native
        def receipt(plan):
            plan['effective_recipe'].update(dynamic_range='dolby_vision', video_sample_entry='dvh1')
            plan['source'].update(dolby_vision_profile=5, dolby_vision_level=6, dv_bl_compat_id=0)
            plan['transformations']=[dict(name='hls_separate_audio', executor='server', recipe_version='1')]
        result=native.NativeHdr10().start(video={'dv_profile':5, 'dv_bl_compat_id':0},
            device=DV_STB, receipt=receipt)
        body=starts(result)[0]
        self.assertEqual('731', body['file_id'])
        hls=body['client_playback_context']['deliveries']['hls']
        self.assertEqual([5], hls['hdr_details']['dolby_vision_profiles'])
        self.assertTrue(result['outcome']['ok'], result['outcome'])
        self.assertEqual('hls', result['outcome']['plan']['streamFormat'])

    def test_aac_only_stb_refuses_surround_receipt_after_hdr10_selection(self):
        sdk=dict(STB, **AAC_ONLY)
        sdk['DolbyVision:true']='DolbyVision:false'
        result=hdr10.Level50HDR10().start(sdk=sdk)
        body=starts(result)[0]
        self.assertEqual('731', body['file_id'])
        hls=body['client_playback_context']['deliveries']['hls']
        self.assertTrue(hls['hdr_details']['hdr10'])
        self.assertEqual(['aac'], hls['audio_decode_codecs'])
        self.assertEqual([], hls['audio_passthrough_codecs'])
        self.assertFalse(result['outcome']['ok'])
        self.assertNotIn('plan', result['outcome'])
        self.assertEqual(1, sum(r['method']=='DELETE' for r in result['requests']))

    def test_unqualified_stb_p8_uses_hdr10_strip_and_refuses_copied_dv_receipt(self):
        from tests import test_silo_native_hdr10 as native
        for copied_dv in (False, True):
            with self.subTest(copied_dv=copied_dv):
                def receipt(plan):
                    if copied_dv:
                        plan['effective_recipe'].update(dynamic_range='dolby_vision', video_sample_entry='dvh1')
                        plan['transformations']=[dict(name='hls_separate_audio', executor='server', recipe_version='1')]
                result=native.NativeHdr10().start(device=STB, receipt=receipt)
                body=starts(result)[0]
                self.assertEqual('731', body['file_id'])
                hdr=body['client_playback_context']['deliveries']['hls']['hdr_details']
                self.assertTrue(hdr['hdr10'])
                self.assertNotIn(8, hdr['dolby_vision_profiles'])
                self.assertEqual(not copied_dv, result['outcome']['ok'], result['outcome'])
                if copied_dv:
                    self.assertNotIn('plan', result['outcome'])
                else:
                    self.assertEqual('hls', result['outcome']['plan']['streamFormat'])

    def test_qualified_p8_bound_accepts_copy_and_explicit_p7_conversion(self):
        from tests import test_silo_native_hdr10 as native
        device={'DolbyVision:true':'DolbyVision:true',
                'return {major:"16",minor:"0",revision:"4",build:"834"}':
                'return {major:"15",minor:"3",revision:"4",build:"2402"}'}
        for source_profile, compat in ((8,1), (7,6)):
            with self.subTest(source_profile=source_profile):
                def receipt(plan):
                    plan['source'].update(dolby_vision_profile=source_profile,dolby_vision_level=6,dv_bl_compat_id=compat)
                    plan['effective_recipe'].update(dynamic_range='dolby_vision',video_sample_entry='dvh1')
                    plan['transformations']=[dict(name='hls_separate_audio',executor='server',recipe_version='1')]
                    if source_profile==7:
                        plan['transformations'].append(dict(name='server_dv7_to_dv81',executor='server',recipe_version='1'))
                result=native.NativeHdr10().start(device=device,video={'dv_profile':source_profile,'dv_bl_compat_id':compat},
                    features=['native_hls_separate_audio_v1','server_dv7_to_dv81_v1'],receipt=receipt)
                self.assertEqual('731', starts(result)[0]['file_id'])
                self.assertTrue(result['outcome']['ok'], result['outcome'])
                self.assertEqual('hls',result['outcome']['plan']['streamFormat'])

    def test_p5_receipt_requires_typed_level_and_compatible_base(self):
        from tests import test_silo_native_hdr10 as native
        for level, compat in ((None,0), ('6',0), (10,0), (6,1)):
            with self.subTest(level=level,compat=compat):
                def receipt(plan):
                    plan['source'].update(dolby_vision_profile=5,dolby_vision_level=level,dv_bl_compat_id=compat)
                    plan['effective_recipe'].update(dynamic_range='dolby_vision',video_sample_entry='dvh1')
                    plan['transformations']=[dict(name='hls_separate_audio',executor='server',recipe_version='1')]
                result=native.NativeHdr10().start(device=DV_STB,video={'dv_profile':5,'dv_bl_compat_id':0},receipt=receipt)
                self.assertEqual('731', starts(result)[0]['file_id'])
                self.assertFalse(result['outcome']['ok'])
                self.assertNotIn('plan',result['outcome'])

    def test_hdr10_strip_candidate_cannot_return_unqualified_original_p8(self):
        from tests import test_silo_native_hdr10 as native
        def receipt(plan):
            plan['delivery']='original_http'
            plan['stream'].update(protocol='original_http',container='mkv')
            plan['source'].update(dolby_vision_profile=8,dolby_vision_level=6,dv_bl_compat_id=1)
            # Original bytes need no generated recipe; source DV still constrains them.
            plan.pop('effective_recipe',None)
            plan['transformations']=[]
        result=native.NativeHdr10().start(device=STB,receipt=receipt)
        self.assertEqual('731', starts(result)[0]['file_id'])
        self.assertFalse(result['outcome']['ok'])
        self.assertNotIn('plan',result['outcome'])

    def test_stock_p5_absent_zero_requires_complete_source_and_never_repairs_null(self):
        from tests import test_silo_native_hdr10 as native
        # Stock's successful P5 DTO omits compatibility zero; retain that wire
        # shape without retaining its private identity, URL, headers or artwork.
        for control in ('absent', 'present_null', 'unproven_base'):
            with self.subTest(control=control):
                def receipt(plan):
                    plan['source'].update(dolby_vision_profile=5,dolby_vision_level=6)
                    plan['source'].pop('dv_bl_compat_id',None)
                    if control=='present_null':plan['source']['dv_bl_compat_id']=None
                    if control=='unproven_base':plan['source']['dv_base_layer_proven']=False
                    plan['effective_recipe'].update(dynamic_range='dolby_vision',video_sample_entry='dvh1')
                    plan['transformations']=[dict(name='hls_separate_audio',executor='server',recipe_version='1')]
                result=native.NativeHdr10().start(device=DV_STB,video={'dv_profile':5,'dv_bl_compat_id':0},receipt=receipt)
                self.assertEqual('731', starts(result)[0]['file_id'])
                self.assertEqual(control=='absent',result['outcome']['ok'],result['outcome'])

    def test_replan_refuses_copied_dv_without_requested_output_bounds(self):
        from tests import test_silo_replan_task as recovery
        decision=json.loads((continuation.legacy.FIXTURES/'playback_decision_plan.json').read_text())
        plan=decision['playback_plan']
        plan.update(delivery='server_remux_hls',
            selected_tracks=recovery.values.TRACKS,
            effective_recipe=dict(video_codec='hevc',audio_codec='aac',audio_channels=2,
                dynamic_range='dolby_vision',video_sample_entry='dvh1'),
            transformations=[dict(name='hls_separate_audio',executor='server',recipe_version='1')])
        plan['source'].update(dolby_vision_profile=5,dolby_vision_level=6,dv_bl_compat_id=0)
        plan['stream'].update(protocol='hls',container='hls')
        result=recovery.SiloReplanTaskTests().call(decision=decision,
            capability_features=['native_hls_separate_audio_v1'])
        bodies=[json.loads(r['body']) for r in result['requests'] if r['method']=='POST']
        self.assertEqual(1,len(bodies))
        hdr=bodies[0]['client_playback_context']['deliveries']['hls'].get('hdr_details',{})
        self.assertEqual([],hdr.get('dolby_vision_profiles',[]))
        self.assertFalse(result['outcome']['ok'])
        self.assertEqual('unsupported_stream',result['outcome']['errorCode'])
