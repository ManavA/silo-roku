"""Source-bound level-5.0 evidence after an unknown generic HEVC query.

Synthetic SDK/HTTP fixtures exercise actual runJob and outgoing requests; they
are not measured decoder capabilities or physical playback proof.
"""
import json
import unittest
from unittest.mock import patch

from tests import test_silo_level50_hdr10 as level50
from tests import test_silo_compat_continuation as task


class Level50UnknownGeneric(unittest.TestCase):
    def sdk(self, generic='return invalid', exact='return {result:true}', avc=True):
        return {'if m.rejectMain10 = true': ('if format.codec="mpeg4 avc" then return {result:false}\n        ' if not avc else '') + '''if format.codec="hevc" and format.profile=invalid then ''' + generic + '''
        if format.codec="hevc" and format.level="5.1" then return {result:false}
        if format.codec="hevc" and format.container<>invalid and format.level="5.0" then ''' + exact + '''
        if m.rejectMain10 = true'''}

    def start(self, generic='return invalid', *, exact='return {result:true}', avc=True, **kwargs):
        return level50.Level50HDR10().start(sdk=self.sdk(generic, exact, avc), **kwargs)

    def test_unknown_generic_retains_exact_source_level50_hdr10_in_start(self):
        result = self.start()
        posts = [json.loads(r['body']) for r in result['requests'] if '/playback/start' in r['url']]
        self.assertEqual(['731'], [p['file_id'] for p in posts], result['outcome'])
        self.assertTrue(result['outcome']['ok'], result['outcome'])
        self.assertTrue(any(q == dict(codec='hevc', container='mkv', profile='main 10', level='5.0') for q in result['videoQueries']), result['videoQueries'])
        caps = posts[0]['client_capabilities']
        hls = posts[0]['client_playback_context']['deliveries']['hls']
        self.assertIn('hevc', caps['codecs_video'])
        self.assertIn('hevc', hls['video_codecs'])
        progressive = posts[0]['client_playback_context']['deliveries']['progressive']
        self.assertFalse(progressive['enabled'])
        self.assertNotIn('hevc', progressive['video_codecs'])
        self.assertTrue(caps['hdr_details']['hdr10'])
        self.assertEqual(30, caps['hdr_details']['hdr10_max_frame_rate'])
        self.assertEqual([], caps['hdr_details']['dolby_vision_profiles'])
        self.assertFalse(result['originalFlag'])
        self.assertFalse(result['p8Flag'])

    def assert_not_projected(self, result):
        posts = [json.loads(r['body']) for r in result['requests'] if '/playback/start' in r['url']]
        self.assertTrue(posts, result['outcome'])
        self.assertTrue(all(p['file_id'] != '731' for p in posts))
        for post in posts:
            self.assertNotIn('hevc', post['client_capabilities']['codecs_video'])
            self.assertFalse(post['client_capabilities']['hdr_details']['hdr10'])
        self.assertNotEqual('task_failed', result['outcome'].get('errorCode'))

    def test_explicit_generic_false_and_closest_format_never_authorize_hevc(self):
        for answer in ('return {result:false}', 'return {result:false,updated:"profile",profile:"main 10",level:"5.0"}'):
            with self.subTest(answer=answer):
                self.assert_not_projected(self.start(generic=answer))

    def test_unknown_generic_requires_positive_exact_container_level50_query(self):
        result = self.start(exact='return {result:false}')
        self.assert_not_projected(result)
        self.assertTrue(any(q == dict(codec='hevc', container='mkv', profile='main 10', level='5.0') for q in result['videoQueries']), result['videoQueries'])

    def test_unknown_generic_cannot_bypass_source_bounds(self):
        result = self.start(source_change=lambda version, wire: version['video_tracks'][0].update(width=4096))
        self.assert_not_projected(result)

    def test_unknown_generic_retains_owned_cleanup_on_post_start_output_drift(self):
        result = self.start(race='start_output')
        posts = [json.loads(r['body']) for r in result['requests'] if '/playback/start' in r['url']]
        self.assertEqual(['731'], [p['file_id'] for p in posts])
        self.assertFalse(result['outcome']['ok'])
        self.assertNotIn('plan', result['outcome'])
        self.assertNotEqual('task_failed', result['outcome'].get('errorCode'))
        deletes = [r for r in result['requests'] if r['method'] == 'DELETE']
        self.assertEqual(1, len(deletes))
        self.assertTrue(deletes[0]['url'].endswith('/playback/session-fixture-01'))
        self.assertEqual('server-install', json.loads(deletes[0]['body'])['installation_id'])

    def replan(self, *, reject_exact=False):
        helper = level50.Level50HDR10()
        actual_start = helper.start

        def start():
            result = actual_start(sdk=self.sdk())
            if reject_exact:
                helper.device.update(self.sdk(exact='return {result:false}'))
            return result
        with patch.object(helper, 'start', side_effect=start):
            return helper.replan()

    def test_replan_rebuilds_exact_source_projection_from_fresh_evidence(self):
        result = self.replan()
        self.assertTrue(result['outcome']['ok'], result['outcome'])
        self.assertEqual(['GET', 'GET', 'POST'], [r['method'] for r in result['requests']])
        body = json.loads(result['requests'][-1]['body'])
        self.assertIn('hevc', body['client_capabilities']['codecs_video'])
        self.assertIn('hevc', body['client_playback_context']['deliveries']['hls']['video_codecs'])
        self.assertTrue(body['client_capabilities']['hdr_details']['hdr10'])
        self.assertEqual('731', result['outcome']['plan']['sourceHDR10Projection']['fileId'])

    def test_replan_rechecks_exact_decoder_support_before_new_allocation(self):
        result = self.replan(reject_exact=True)
        self.assertFalse(result['outcome']['ok'])
        self.assertEqual('unsupported_stream', result['outcome']['errorCode'])
        self.assertEqual(['GET', 'GET'], [r['method'] for r in result['requests']])

    def test_omitted_internal_evidence_cannot_invent_generic_unknown(self):
        # Direct optional-argument guard: actual assembler/context/source proof,
        # with SDK leaves only. This control is not an additional runJob claim.
        execute = task.run_function

        def launch(files, function, args, *, root):
            bridge = root / 'MissingEvidence.brs'
            bridge.write_text("""
function RunMissingEvidence(session as Object, wire as Object, responses as Object, options as Object, jobChanges as Object, race as String) as Object
 m.fixtureSession=session:m.fixtureRevision=0
 device=FixtureSiloDevice()
 caps=TaskRokuSiloCapabilities(device)
 context=TaskRokuSiloContext(device,caps)
 server=DecodeSiloResponse("playback_capabilities",responses[1].body,{})
 context=TaskNegotiateSiloHLS(context,device,server.data,caps)
 detail=ScopeCatalogData(DecodeSiloResponse("detail",FormatJson(wire),{sourceId:session.sourceId}).data,session.sourceId)
 proof=TaskSiloLevel50HDR10(wire,detail,session.sourceId,"fixture-item","731",0,{qualityPreference:"original"},device,caps,context)
 return {proof:proof,caps:caps}
end function
""")
            return execute([*files, bridge], 'RunMissingEvidence', args, root=root)

        with patch.object(task, 'run_function', side_effect=launch):
            result = self.start()
        self.assertIsNone(result['proof'])
        self.assertNotIn('hevc', result['caps']['codecs_video'])

    def test_legacy_h264_only_hls_lane_is_unchanged_for_unknown_or_healthy_generic(self):
        # A non-copy server feature keeps the actual HLS negotiation on its
        # legacy transcode lane, independently of the source's MKV proof.
        actual_job = task.CompatContinuation.job

        def legacy_server(instance, **kwargs):
            def http(responses):
                caps = json.loads(responses[1]['body'])
                caps['deliveries'] = ['original_http', 'server_transcode_hls']
                responses[1]['body'] = json.dumps(caps)
            kwargs['http'] = http
            return actual_job(instance, **kwargs)

        with patch.object(task.CompatContinuation, 'job', legacy_server):
            results = (self.start(features=['seek_reanchor_v1']),
                       level50.Level50HDR10().start(features=['seek_reanchor_v1']))
        for result in results:
            posts = [json.loads(r['body']) for r in result['requests'] if '/playback/start' in r['url']]
            self.assertEqual(1, len(posts), result['outcome'])
            hls = posts[0]['client_playback_context']['deliveries']['hls']
            self.assertTrue(hls['enabled'])
            self.assertTrue(hls['supported_on_device'])
            self.assertEqual(['h264'], hls['video_codecs'])
            self.assertEqual(['native_hls_playback_v1'], hls['features'])

    def test_reused_evidence_is_reset_by_fresh_explicit_generic_rejection(self):
        execute = task.run_function

        def launch(files, function, args, *, root):
            bridge = root / 'FreshEvidence.brs'
            bridge.write_text("""
function RunFreshEvidence(session as Object, wire as Object, responses as Object, options as Object, jobChanges as Object, race as String) as Object
 m.fixtureSession=session:m.fixtureRevision=0
 device=FixtureSiloDevice():evidence={}
 first=TaskRokuSiloCapabilities(device,evidence):unknown=SpCopy(evidence)
 device.genericResult=false
 caps=TaskRokuSiloCapabilities(device,evidence)
 context=TaskRokuSiloContext(device,caps)
 server=DecodeSiloResponse("playback_capabilities",responses[1].body,{})
 context=TaskNegotiateSiloHLS(context,device,server.data,caps)
 detail=ScopeCatalogData(DecodeSiloResponse("detail",FormatJson(wire),{sourceId:session.sourceId}).data,session.sourceId)
 proof=TaskSiloLevel50HDR10(wire,detail,session.sourceId,"fixture-item","731",0,{qualityPreference:"original"},device,caps,context,evidence)
 return {proof:proof,unknown:unknown,current:evidence,caps:caps}
end function
""")
            return execute([*files, bridge], 'RunFreshEvidence', args, root=root)

        with patch.object(task, 'run_function', side_effect=launch):
            result = self.start(generic='return {result:m.genericResult}')
        self.assertEqual(dict(genericHevcKnown=False, genericHevcSupported=False), result['unknown'])
        self.assertEqual(dict(genericHevcKnown=True, genericHevcSupported=False), result['current'])
        self.assertIsNone(result['proof'])
        self.assertNotIn('hevc', result['caps']['codecs_video'])

    def test_unproven_hls_output_cannot_bind_a_remux_receipt(self):
        result = self.start(exact='return {result:format.container="mkv"}')
        posts = [json.loads(r['body']) for r in result['requests'] if '/playback/start' in r['url']]
        self.assertEqual(['731'], [p['file_id'] for p in posts])
        lanes = posts[0]['client_playback_context']['deliveries']
        self.assertIn('hevc', lanes['original_http']['video_codecs'])
        self.assertNotIn('hevc', lanes['hls']['video_codecs'])
        self.assertNotIn('hevc', lanes['progressive']['video_codecs'])
        self.assertTrue(any(q == dict(codec='hevc', container='mp4', profile='main 10', level='5.0') for q in result['videoQueries']))
        # The synthetic server still returns the old HEVC split-HLS receipt;
        # it contradicts this request's HLS lane and must be owned-rejected.
        self.assertFalse(result['outcome']['ok'], result['outcome'])
        self.assertNotIn('plan', result['outcome'])
        self.assertEqual(1, sum(r['method'] == 'DELETE' for r in result['requests']))

    def test_both_hls_packagings_require_every_exact_output_container(self):
        for rejected in ('ts', 'mp4'):
            with self.subTest(rejected=rejected):
                result = self.start(exact='return {result:format.container<>"'+rejected+'"}',
                                    features=['native_hls_mpegts_v1', 'native_hls_separate_audio_v1'])
                posts = [json.loads(r['body']) for r in result['requests'] if '/playback/start' in r['url']]
                self.assertEqual(['731'], [p['file_id'] for p in posts])
                hls = posts[0]['client_playback_context']['deliveries']['hls']
                self.assertNotIn('hevc', hls['video_codecs'])
                self.assertEqual(['native_hls_playback_v1', 'native_hls_mpegts_v1', 'native_hls_separate_audio_v1'], hls['features'])
                for container in ('ts', 'mp4'):
                    self.assertIn(dict(codec='hevc', container=container, profile='main 10', level='5.0'), result['videoQueries'])
                self.assertFalse(result['outcome']['ok'])
                self.assertNotIn('plan', result['outcome'])

    def test_disabled_hls_lane_cannot_be_promoted_by_source_container_proof(self):
        result = self.start(features=['seek_reanchor_v1'])
        posts = [json.loads(r['body']) for r in result['requests'] if '/playback/start' in r['url']]
        self.assertEqual(['731'], [p['file_id'] for p in posts])
        hls = posts[0]['client_playback_context']['deliveries']['hls']
        self.assertFalse(hls['enabled'])
        self.assertFalse(hls['supported_on_device'])
        self.assertEqual([], hls['video_codecs'])
        self.assertEqual([], hls['features'])

    def test_unknown_generic_needs_an_already_enabled_proven_hevc_lane(self):
        result = self.start(avc=False)
        self.assertFalse(result['outcome']['ok'])
        self.assertEqual('unsupported_device', result['outcome']['errorCode'])
        self.assertFalse(any(r['method'] in ('POST', 'DELETE') for r in result['requests']))

    def assert_owned_close(self, result):
        deletes = [r for r in result['requests'] if r['method'] == 'DELETE']
        self.assertEqual(1, len(deletes))
        self.assertTrue(deletes[0]['url'].endswith('/playback/session-fixture-01'))
        body = json.loads(deletes[0]['body'])
        self.assertEqual('server-install', body['installation_id'])
        self.assertRegex(body['stop_id'], r'^[0-9a-f-]{36}$')

    def test_ts_only_lane_cannot_accept_an_unadvertised_split_mp4_receipt(self):
        result = self.start(features=['native_hls_mpegts_v1'])
        posts = [json.loads(r['body']) for r in result['requests'] if '/playback/start' in r['url']]
        self.assertEqual(['731'], [p['file_id'] for p in posts])
        hls = posts[0]['client_playback_context']['deliveries']['hls']
        self.assertIn('hevc', hls['video_codecs'])
        self.assertEqual(['native_hls_playback_v1', 'native_hls_mpegts_v1'], hls['features'])
        self.assertIn(dict(codec='hevc', container='ts', profile='main 10', level='5.0'), result['videoQueries'])
        self.assertNotIn(dict(codec='hevc', container='mp4', profile='main 10', level='5.0'), result['videoQueries'])
        self.assertFalse(result['outcome']['ok'])
        self.assertEqual('invalid_response', result['outcome']['errorCode'])
        self.assertNotIn('plan', result['outcome'])
        self.assert_owned_close(result)

    def test_output_query_drift_after_start_retires_the_exact_owned_lease(self):
        # Stateful decoder behavior is entirely at the SDK boundary: candidate
        # and selected request succeed; the post-allocation readback declines.
        sdk = task.legacy.BOUNDARIES + """
function FixtureOutputDecoder(device as Object, format as Object) as Object
 if format.container<>"mp4" then return {result:true}
 if device.outputCount=invalid then device.outputCount=0
 device.outputCount++
 return {result:device.outputCount<=2}
end function
"""
        with patch.object(task.legacy, 'BOUNDARIES', sdk):
            result = self.start(exact='return FixtureOutputDecoder(m,format)')
        posts = [json.loads(r['body']) for r in result['requests'] if '/playback/start' in r['url']]
        self.assertEqual(['731'], [p['file_id'] for p in posts])
        self.assertGreaterEqual(result['videoQueries'].count(dict(codec='hevc', container='mp4', profile='main 10', level='5.0')), 3)
        self.assertFalse(result['outcome']['ok'])
        self.assertEqual('session_changed', result['outcome']['errorCode'])
        self.assertNotIn('plan', result['outcome'])
        self.assert_owned_close(result)
