"""Ordinary runJob/SDK/HTTP behavior for source-bound 4K30 HDR10 evidence.

Synthetic decoder and HTTP answers establish host policy only, not device output.
"""
import copy
import json
import unittest
from pathlib import Path
from tests import test_silo_compat_continuation as task

FIXTURE = Path(__file__).parent / 'fixtures/silo/hdr10_split_0589_source_derived.json'


class Level50HDR10(unittest.TestCase):
    def start(self, source_change=None, receipt_change=None, options=None, sdk=None, race='', features=None):
        def fixture(wire, decision):
            video = wire['versions'][0]['video_tracks'][0]
            for key in list(video):
                if key.startswith('dv_'):
                    del video[key]
            video['video_range_type'] = 'hdr10'
            wire['playback_variants'][0]['default_file_id'] = '732'
            wire['playback_variants'][0]['parts'][0]['default_file_id'] = '732'
            decision.clear()
            decision.update(json.loads(FIXTURE.read_text()))
            plan = decision['playback_plan']
            plan['source']['dynamic_range'] = 'hdr10'
            for key in list(plan['source']):
                if key.startswith('dv_') or key.startswith('dolby_vision_'):
                    del plan['source'][key]
            plan['source']['dv_enhancement_layer'] = 'none'
            plan['transformations'] = [t for t in plan['transformations'] if t['name'] == 'hls_separate_audio']
            if source_change:
                source_change(wire['versions'][0], wire)
            if receipt_change:
                receipt_change(plan)
            self.wire = copy.deepcopy(wire)
            self.decision = copy.deepcopy(decision)
        device = {'if m.rejectMain10 = true': '''if format.codec="hevc" and format.level="5.1" then return {result:false}
        if m.rejectMain10 = true'''}
        device['return "2160p60"'] = 'return "2160p30"'
        device.update(sdk or {})
        self.device = device
        params = dict(startPositionMs=0, fileId='732')
        params.update(options or {})
        return task.CompatContinuation().job(enabled=False, mutate=fixture, features=['native_hls_separate_audio_v1'] if features is None else features, options=params, device=device, race=race)

    def starts(self, result):
        return [json.loads(r['body']) for r in result['requests'] if '/playback/start' in r['url']]

    def test_exact_level50_hdr10_candidate_beats_sdr_anchor_without_aggregate_support(self):
        result = self.start()
        bodies = self.starts(result)
        self.assertEqual(['731'], [b['file_id'] for b in bodies], result['outcome'])
        self.assertTrue(result['outcome']['ok'], result['outcome'])
        caps = bodies[0]['client_capabilities']
        self.assertTrue(caps['hdr'])
        self.assertEqual({'hdr10': True, 'hdr10_plus': False, 'hlg': False, 'dolby_vision_profiles': [], 'hdr10_max_width': 3840, 'hdr10_max_height': 2160, 'hdr10_max_frame_rate': 30, 'hdr10_max_bitrate_kbps': 54000}, caps['hdr_details'])
        self.assertEqual('2160p', caps['max_resolution'])
        self.assertFalse(result['originalFlag'])
        self.assertFalse(result['p8Flag'])

    def test_display_change_after_allocation_retires_the_owned_lease(self):
        result = self.start(race='start_output')
        self.assertFalse(result['outcome']['ok'], result['outcome'])
        self.assertNotIn('plan', result['outcome'])
        self.assertEqual(['GET', 'GET', 'POST', 'DELETE'], [r['method'] for r in result['requests']])

    def test_track_bitrate_precedence_matches_server_source_and_recipe(self):
        result = self.start(source_change=lambda v, w: v['video_tracks'][0].update(bitrate=52000000), receipt_change=lambda p: (p['source'].update(bitrate_kbps=52000), p['effective_recipe'].update(bitrate_kbps=52000)))
        self.assertTrue(result['outcome']['ok'], result['outcome'])
        self.assertEqual(52000, self.starts(result)[0]['client_capabilities']['hdr_details']['hdr10_max_bitrate_kbps'])

    def assert_unprojected(self, result):
        bodies = self.starts(result)
        self.assertTrue(bodies, result['outcome'])
        self.assertTrue(all(not b['client_capabilities'].get('hdr_details', {}).get('hdr10', False) for b in bodies))
        self.assertTrue(all(b['file_id'] != '731' for b in bodies))

    def test_malformed_dv_flags_cannot_become_absent_source_evidence(self):
        self.assert_unprojected(self.start(source_change=lambda v, w: v['video_tracks'][0].update(dv_config_present='true')))


    def replan(self, fresh_change=None, receipt_change=None, race=''):
        from unittest.mock import patch
        from tests import test_silo_replan_task as recovery
        started = self.start()
        self.assertTrue(started['outcome']['ok'], started['outcome'])
        plan = started['outcome']['plan']
        wire = self.wire
        decision = self.decision
        if fresh_change:
            fresh_change(wire['versions'][0], wire)
        if receipt_change:
            receipt_change(decision['playback_plan'])
        params = dict(sessionId=plan['sessionId'], plan=plan, qualityPreference='original', positionMs=12000, replanRequestId='level50-replan-01', failureClassification='decoder_failure')
        scope = dict(provider='silo', sourceId=plan['sourceId'], profileId='fixture-owner', generation=7)
        response = json.dumps(dict(statusCode=200, body=json.dumps(wire)))
        literal = '"' + response.replace('"', '""') + '"'
        boundary = recovery.BOUNDARY.replace('m.requests=[]:m.timeouts=[]:m.responses=responses',
            'responses=[responses[0],ParseJson(' + literal + '),responses[1]]\n' +
            'cap=ParseJson(responses[0].body):cap.installation_id=params.plan.installationId:responses[0].body=FormatJson(cap)\n' +
            'decision=ParseJson(responses[2].body):decision.session_id=params.sessionId:decision.playback_plan.session_id=params.sessionId:responses[2].body=FormatJson(decision)\n' +
            'm.requests=[]:m.timeouts=[]:m.responses=responses')
        boundary = boundary.replace('sourceId:"silo:synthetic",profileId:"owner"', 'sourceId:"silo:https://silo.example",profileId:"fixture-owner"')
        boundary = boundary.replace('outcome=ExecuteApiAction("silo",action,params,scope)',
            'job={provider:"silo",action:action,sourceId:scope.sourceId,profileId:scope.profileId,generation:scope.generation,requestId:42,params:params}\n' +
            'm.top=CreateObject("roSGNode","Node"):m.top.AddFields({cancelled:false,job:job,result:{}})\nrunJob():outcome=m.top.result')
        sdk = recovery.legacy.BOUNDARIES
        for old, new in self.device.items():
            sdk = sdk.replace(old, new)
        sdk = sdk.replace('return "1080p"', 'return "2160p30"')
        if race:
            effect = 'm.top.cancelled=true' if race == 'cancel' else 'm.fixtureSession=FixtureDeepClone(m.fixtureSession):m.fixtureSession.profileToken="changed-pin"'
            sdk = sdk.replace('response = m.responses.Shift()', 'if m.requests.Count()=2 then ' + effect + '\n    response = m.responses.Shift()')
        with patch.object(recovery, 'BOUNDARY', boundary), patch.object(recovery.legacy, 'BOUNDARIES', sdk):
            return recovery.SiloReplanTaskTests().call(params=params, decision=decision, scope=scope, capability_features=['native_hls_separate_audio_v1'])

    def test_replan_rebuilds_the_same_bounded_projection_from_fresh_detail(self):
        result = self.replan()
        self.assertEqual(['GET', 'GET', 'POST'], [r['method'] for r in result['requests']])
        self.assertTrue(result['outcome']['ok'], result['outcome'])
        body = json.loads(result['requests'][-1]['body'])
        self.assertTrue(body['client_capabilities']['hdr_details']['hdr10'])
        self.assertEqual(30, body['client_capabilities']['hdr_details']['hdr10_max_frame_rate'])
        self.assertEqual('731', result['outcome']['plan']['sourceHDR10Projection']['fileId'])

    def test_exact_probe_negative_unknown_and_malformed_cannot_project(self):
        for answer in ('return {result:false}', 'return {result:1}', 'return invalid', 'throw "synthetic-sdk-error"'):
            with self.subTest(answer=answer):
                sdk = {'        return {result:true}': '        if format.codec="hevc" and format.container<>invalid and format.level="5.0" then ' + answer + '\n        return {result:true}'}
                self.assert_unprojected(self.start(sdk=sdk))

    def test_source_bounds_and_cap_never_broaden_the_projection(self):
        cases = [
            (lambda v, w: v['video_tracks'][0].update(level=153), {}),
            (lambda v, w: v['video_tracks'][0].update(frame_rate='60'), {}),
            (lambda v, w: v['video_tracks'][0].pop('frame_rate'), {}),
            (lambda v, w: v['video_tracks'][0].update(width=4096), {}),
            (lambda v, w: v.update(bitrate=0), {}),
            (None, {'bandwidthCapKbps': 53000}),
        ]
        for index, (change, options) in enumerate(cases):
            with self.subTest(index=index):
                self.assert_unprojected(self.start(source_change=change, options=options))

    def test_typed_display_and_global_hevc_rejection_stay_authoritative(self):
        for sdk in [
            {'return {Hdr10:true,Hdr10Plus:false,HLG:false,DolbyVision:true}': 'return {Hdr10:"true",DolbyVision:false}'},
            {'return {Hdr10:true,Hdr10Plus:false,HLG:false,DolbyVision:true}': 'return {Hdr10:false,DolbyVision:false}'},
            {'if format.codec="hevc" and format.level="5.1" then return {result:false}': 'if format.codec="hevc" and format.profile=invalid then return {result:false}\n        if format.codec="hevc" and format.level="5.1" then return {result:false}'},
        ]:
            with self.subTest(sdk=sdk):
                self.assert_unprojected(self.start(sdk=sdk))

    def test_dv_hlg_and_hdr10_plus_cannot_use_plain_hdr10_evidence(self):
        for facts in [dict(dv_profile=8, dv_config_present=True), dict(video_range_type='hlg', color_transfer='arib-std-b67'), dict(hdr10_plus=True)]:
            with self.subTest(facts=facts):
                self.assert_unprojected(self.start(source_change=lambda v, w: v['video_tracks'][0].update(facts)))

    def test_contradictory_copy_receipts_are_owned_rejected(self):
        changes = [
            lambda p: p['source'].update(width=1920),
            lambda p: p['source'].update(media_file_id='foreign-file'),
            lambda p: p['source'].update(frame_rate=60),
            lambda p: p['effective_recipe'].update(bitrate_kbps=53000),
            lambda p: p['effective_recipe'].update(dynamic_range='sdr'),
            lambda p: p['transformations'].append(dict(name='video_to_hevc', executor='server', recipe_version='1')),
        ]
        for index, change in enumerate(changes):
            with self.subTest(index=index):
                result = self.start(receipt_change=change)
                self.assertFalse(result['outcome']['ok'], result['outcome'])
                self.assertNotIn('plan', result['outcome'])
                self.assertEqual(['GET', 'GET', 'POST', 'DELETE'], [r['method'] for r in result['requests']])

    def test_plain_sdr_level50_selection_already_works_without_hdr_projection(self):
        def source(v, w):
            v['hdr'] = False
            video = v['video_tracks'][0]
            video.pop('video_range_type')
            video.pop('color_transfer')
        def receipt(p):
            p['source']['dynamic_range'] = 'sdr'
            p['effective_recipe']['dynamic_range'] = 'sdr'
            p['claims']['video']['hdr10'] = False
        result = self.start(source_change=source, receipt_change=receipt)
        self.assertTrue(result['outcome']['ok'], result['outcome'])
        self.assertEqual(['731'], [b['file_id'] for b in self.starts(result)])
        self.assertFalse(self.starts(result)[0]['client_capabilities']['hdr_details']['hdr10'])
        self.assertNotIn('sourceHDR10Projection', result['outcome']['plan'])

    def test_manual_mp4_uses_its_actual_container_and_keeps_projection_local(self):
        result = self.start(source_change=lambda v, w: v.update(container='mp4'), receipt_change=lambda p: p['source'].update(container='mp4'), options=dict(fileId='731', autoVersion=False, bandwidthCapKbps=54000))
        self.assertTrue(result['outcome']['ok'], result['outcome'])
        self.assertIn(dict(codec='hevc', container='mp4', profile='main 10', level='5.0'), result['videoQueries'])
        body = self.starts(result)[0]
        hdr = body['client_capabilities']['hdr_details']
        context = body['client_playback_context']
        self.assertEqual(hdr, context['output']['hdr_details'])
        self.assertEqual(hdr, context['output']['display']['hdr_types'])
        self.assertEqual(hdr, context['deliveries']['hls']['hdr_details'])
        self.assertFalse(body['allow_alternate_versions'])

    def test_replan_refuses_changed_fresh_source_before_allocation(self):
        result = self.replan(fresh_change=lambda v, w: v['video_tracks'][0].update(frame_rate='30'))
        self.assertFalse(result['outcome']['ok'], result['outcome'])
        self.assertEqual(['GET', 'GET'], [r['method'] for r in result['requests']])

    def test_replan_refuses_stale_identity_before_allocation(self):
        result = self.replan(race='pin')
        self.assertFalse(result['outcome']['ok'], result['outcome'])
        self.assertEqual(['GET', 'GET'], [r['method'] for r in result['requests']])

    def test_bad_replan_receipt_retains_new_lease_cleanup_authority(self):
        result = self.replan(receipt_change=lambda p: p['effective_recipe'].update(frame_rate=60))
        self.assertFalse(result['outcome']['ok'], result['outcome'])
        self.assertTrue(result['outcome']['leaseUncertain'])
        self.assertEqual('plan-0002', result['outcome']['controlReceipt']['planId'])
        self.assertEqual(['GET', 'GET', 'POST'], [r['method'] for r in result['requests']])

    def test_1080_output_does_not_gain_2160_claim_even_for_a_smaller_level50_source(self):
        result = self.start(source_change=lambda v, w: v['video_tracks'][0].update(width=1920, height=1080), sdk={'return "2160p60"': 'return "1080p"'})
        self.assert_unprojected(result)
        self.assertTrue(all(b['client_capabilities'].get('max_resolution') != '2160p' for b in self.starts(result)))


    def test_bounded_projection_retains_negotiated_seek_authority(self):
        result = self.start(features=['native_hls_separate_audio_v1', 'seek_reanchor_v1'], receipt_change=lambda p: p['transformations'][0].pop('validated_claims'))
        self.assertTrue(result['outcome']['ok'], result['outcome'])
        descriptor = result['outcome']['plan'].get('seekReanchor')
        self.assertIsNotNone(descriptor)
        hdr = descriptor['request']['client_capabilities']['hdr_details']
        self.assertEqual(30, hdr['hdr10_max_frame_rate'])
        self.assertEqual(54000, hdr['hdr10_max_bitrate_kbps'])


    def test_duplicate_fresh_source_inventory_never_allocates(self):
        result = self.start(source_change=lambda v, w: w['versions'].append(copy.deepcopy(v)))
        self.assertFalse(result['outcome']['ok'], result['outcome'])
        self.assertEqual([], self.starts(result))
