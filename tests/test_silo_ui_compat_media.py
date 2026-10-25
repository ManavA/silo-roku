"""Actual Task continuation -> Scene -> retained holder -> native Player callbacks.

SDK node/device/HTTP/session and callback scheduling are the only substitutes.
This host evidence does not qualify Roku redirect or media delivery behavior.
"""
import copy
import json
import unittest
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from tests import test_silo_ui_compat_continuation as scene_fixture
from tests import test_silo_compat_playback_task as holder_fixture
from tests import test_silo_compat_continuation as native_fixture
from tests.test_silo_compat_playback_task import TOKEN


class CompatMedia(unittest.TestCase):
    def media(self, control, change=None, explicit=False, **kwargs):
        envelope = copy.deepcopy(scene_fixture.SiloUICompatContinuation.envelope)
        if explicit:
            envelope = native_fixture.CompatContinuation().job(options={'qualityExplicit': True})['outcome']
        data = dict(envelope=envelope, wire=copy.deepcopy(scene_fixture.SiloUICompatContinuation.wire),
                    control=control, qualityExplicit=explicit)
        return holder_fixture.CompatPlaybackTask().transcript(scene=data, change=change, **kwargs)

    def test_scene_binding_authority_uses_only_scene_loaded_revision_reader(self):
        root = Path(__file__).resolve().parents[1]
        paths = [s.get('uri').removeprefix('pkg:/') for s in
                 ET.parse(root/'components/SiloUIScene.xml').getroot().findall('script')]
        definitions = set(re.findall(r'(?im)^\s*(?:function|sub)\s+(\w+)\(',
                                    '\n'.join((root/p).read_text() for p in paths)))
        self.assertIn('DetailPhotoSessionRevision', definitions)
        self.assertIn('AppRegistrySection', definitions)
        coordinator = (root/'components/SiloUICompatPlayback.brs').read_text()
        self.assertNotRegex(coordinator, r'(?<![A-Za-z])SessionRevision\(')
        self.assertRegex(coordinator, r'DetailPhotoSessionRevision\(')
        detail = (root/'components/SiloUIDetail.brs').read_text()
        reader = re.search(r'(?ms)^function DetailPhotoSessionRevision\(.*?^end function',detail).group(0)
        self.assertIn('AppRegistrySection("silo")',reader)
        self.assertNotRegex(reader,r'(?<![A-Za-z])SessionRevision\(')

    @classmethod
    def setUpClass(cls):
        scene_fixture.SiloUICompatContinuation.setUpClass()

    def test_admitted_foreground_preparation_binds_privately_through_player_start(self):
        result = scene_fixture.SiloUICompatContinuation().scene("media")
        self.assertTrue(result['scene']['bound'],
                        'admitted prepared holder must bind through actual PlayerBind/Start')
        self.assertTrue(result['scene']['privatePayloadCleared'])
        self.assertEqual('silo_compat', result['scene']['plan']['transport'])
        self.assertNotIn(TOKEN, json.dumps(result['scene']['plan']))
        self.assertNotIn('master.m3u8', json.dumps(result['scene']['plan']))
        self.assertEqual(['Authorization: Bearer '+TOKEN], result['scene']['contentHeaders'])
        self.assertEqual({'Authorization': 'Bearer '+TOKEN}, result['scene']['agentHeaders'])
        self.assertNotIn(TOKEN, json.dumps(result['results']))
        self.assertNotIn('master.m3u8', json.dumps(result['results']))


    def test_first_current_native_playing_reports_and_confirms_exact_active_owner(self):
        result = scene_fixture.SiloUICompatContinuation().scene("media")
        requests = result['requests']
        reports = [q for q in requests if q['url'].endswith('/Sessions/Playing')]
        self.assertEqual(1, len(reports), 'first native playing must reach the private holder')
        self.assertEqual('Bearer '+TOKEN, reports[0]['headers'].get('Authorization'))
        self.assertNotIn('X-Emby-Token', reports[0]['headers'])
        report = json.loads(reports[0]['body'])
        self.assertEqual(('play-fixture', 250000000, 1, -1, False),
                         (report['PlaySessionId'], report['PositionTicks'], report['AudioStreamIndex'],
                          report['SubtitleStreamIndex'], report['IsPaused']))
        self.assertNotIn('generation', report)
        self.assertTrue(any(q['url'].endswith('/Sessions') for q in requests))

    def test_paused_source_progress_uses_holder_not_native_report(self):
        result = scene_fixture.SiloUICompatContinuation().scene("media_progress")
        reports = [q for q in result['requests'] if q['url'].endswith('/Sessions/Playing/Progress')]
        self.assertEqual(1, len(reports), 'actual PlayerReport must dispatch to retained compatibility holder')
        self.assertEqual('Bearer '+TOKEN, reports[0]['headers'].get('Authorization'))
        self.assertNotIn('X-Emby-Token', reports[0]['headers'])
        report = json.loads(reports[0]['body'])
        self.assertEqual((300000000, True, 1),
                         (report['PositionTicks'], report['IsPaused'], report['AudioStreamIndex']))
        self.assertNotIn(TOKEN, json.dumps(result['results']))


    def test_back_drains_exact_started_owner_and_retires_both_header_stores(self):
        result = scene_fixture.SiloUICompatContinuation().scene("media_close")
        self.assertTrue(result['scene']['released'], result)
        self.assertFalse(result['scene']['bound'])
        self.assertEqual([], result['scene']['retiredHeaders'])
        self.assertEqual({}, result['scene']['agentHeaders'])
        self.assertTrue(result['scene']['retainedContentCleared'])
        compat = [q for q in result['requests'] if 'compat.example' in q['url']]
        authenticated = [q for q in compat if not any(p in q['url'] for p in
                         ('/System/Info/Public', '/QuickConnect/Initiate', '/AuthenticateWithQuickConnect'))]
        self.assertTrue(authenticated)
        for request in authenticated:
            self.assertEqual('Bearer '+TOKEN, request['headers'].get('Authorization'))
            self.assertNotIn('X-Emby-Token', request['headers'])
            self.assertNotIn(TOKEN, request['url'])
            self.assertNotIn('X-Profile-Token', request['headers'])
        for request in compat:
            self.assertIn('X-Emby-Authorization', request['headers'])
        for request in compat:
            if request not in authenticated:
                self.assertNotIn('Authorization', request['headers'])
                self.assertNotIn('X-Emby-Token', request['headers'])
        paths = [q['url'] for q in result['requests']]
        self.assertEqual(1, sum('/Sessions/Playing/Stopped' in p for p in paths))
        self.assertEqual(1, sum('/Videos/ActiveEncodings?PlaySessionId=play-fixture' in p for p in paths))
        self.assertEqual(1, sum('/Sessions/Logout' in p for p in paths))
        self.assertTrue(result['results'][-1]['credentialRevoked'])
        self.assertFalse(result['results'][-1]['mediaNeverRequested'])


    def test_released_unobserved_start_keeps_authority_after_empty_inventory(self):
        def no_active(values):
            values['sessions'] = []
        result = scene_fixture.SiloUICompatContinuation().scene("media_unknown", change=no_active)
        self.assertFalse(result['scene']['released'])
        self.assertTrue(result['scene']['cleanupPending'])
        self.assertTrue(result['scene']['observing'])
        self.assertTrue(result['results'][-1]['cleanupUnconfirmed'])
        self.assertFalse(result['results'][-1]['mediaNeverRequested'])
        self.assertFalse(any('/Sessions/Logout' in q['url'] for q in result['requests']))
        self.assertLessEqual(sum(q['url'].endswith('/Sessions') for q in result['requests']), 4)
        self.assertEqual([], result['scene']['retiredHeaders'])


    def test_nonzero_resume_never_reports_transient_zero_as_source_position(self):
        result = scene_fixture.SiloUICompatContinuation().scene("media_resume")
        reports = [q for q in result['requests'] if q['url'].endswith('/Sessions/Playing/Progress')]
        self.assertEqual(1, len(reports))
        self.assertEqual(250000000, json.loads(reports[0]['body'])['PositionTicks'])


    def test_transport_seek_retires_old_owner_and_reanchors_same_source_without_new_login(self):
        result = scene_fixture.SiloUICompatContinuation().scene("media_seek")
        posts = [q for q in result['requests'] if q['url'].endswith('/PlaybackInfo')]
        self.assertEqual(2, len(posts), 'Transport OK must reanchor through retained holder')
        self.assertEqual(9000000000, json.loads(posts[1]['body'])['StartTimeTicks'])
        self.assertEqual(json.loads(posts[0]['body'])['MediaSourceId'], json.loads(posts[1]['body'])['MediaSourceId'])
        self.assertEqual(1, sum('/AuthenticateWithQuickConnect' in q['url'] for q in result['requests']))
        self.assertFalse(any('/Sessions/Logout' in q['url'] for q in result['requests']))
        self.assertEqual(2, result['scene']['plan']['planGeneration'])
        self.assertNotIn(TOKEN, json.dumps(result['scene']['plan']))


    def test_paused_forward_reverse_generations_then_back_restore_original_chrome_and_captions(self):
        result = scene_fixture.SiloUICompatContinuation().scene("media_roundtrip")
        posts = [json.loads(q['body']) for q in result['requests'] if q['url'].endswith('/PlaybackInfo')]
        self.assertEqual([250000000, 9000000000, 1200000000], [p['StartTimeTicks'] for p in posts])
        self.assertEqual(3, sum(q['url'].endswith('/Sessions/Playing/Stopped') for q in result['requests']))
        self.assertEqual([[], [], []], result['scene']['generationHeaders'])
        self.assertEqual(('detail', 'On', False),
                         (result['scene']['returnView'], result['scene']['captionMode'], result['scene']['muted']))
        self.assertTrue(result['scene']['released'])
        self.assertTrue(result['privateCleared'])
        self.assertEqual(1, sum('/Sessions/Logout' in q['url'] for q in result['requests']))


    def test_custom_controls_cannot_fall_back_to_native_seek_or_expose_native_track_menu(self):
        result = scene_fixture.SiloUICompatContinuation().scene("media_controls")
        self.assertEqual([False, False, False], result['scene']['nativeControls'])
        self.assertFalse(result['scene']['trackDialogOpened'])


    def test_confirmed_failure_close_resumes_lower_native_once_with_history_and_position(self):
        result = scene_fixture.SiloUICompatContinuation().scene("media_failure")
        starts = [q for q in result['requests'] if '/api/v2/playback/start' in q['url']]
        self.assertEqual(1, len(starts), 'confirmed close may resume one lower native request')
        self.assertEqual(('732', 42), (json.loads(starts[0]['body'])['file_id'], json.loads(starts[0]['body'])['start_position']))
        self.assertTrue(result['scene']['attempt']['resumeConsumed'])
        self.assertEqual(1, result['scene']['attempt']['playToken'])
        paths = [q['url'] for q in result['requests']]
        self.assertLess(next(i for i,p in enumerate(paths) if '/Sessions/Logout' in p), paths.index(starts[0]['url']))
        self.assertEqual('732', result['scene']['plan']['versionId'])


    def test_replaced_content_error_cannot_stop_the_replacement(self):
        result = scene_fixture.SiloUICompatContinuation().scene("media_replaced")
        self.assertEqual('play', result['scene']['nativeControl'])
        self.assertFalse(any('/Sessions/Logout' in q['url'] for q in result['requests']))


    def test_explicit_original_failure_ends_with_finite_ui_without_lowering(self):
        result = self.media('media_failure', explicit=True)
        self.assertFalse(any('/api/v2/playback/start' in q['url'] for q in result['requests']))
        self.assertTrue(result['scene']['released'])
        self.assertFalse(result['scene']['loading'])
        self.assertTrue(result['scene']['failureDialog'])
        self.assertTrue(result['scene']['failureMessage'].startswith('#3001:'))
        self.assertFalse(result['scene']['attempt']['resumeConsumed'])


    def test_duplicate_binding_cannot_rebind_and_disposes_its_ephemeral_credentials(self):
        result = self.media('media_duplicate')
        self.assertFalse(result['scene']['duplicateRebound'])
        self.assertTrue(result['scene']['privatePayloadCleared'])
        self.assertNotIn(TOKEN, json.dumps(result['results']))


    def test_each_cleanup_authority_failure_retains_holder_without_native_fallback(self):
        for endpoint, status in [('compat/stopped', 503), ('compat/delete', 503),
                                 ('compat/sessions', 503), ('compat/logout', 503),
                                 ('compat/revocation', 200)]:
            with self.subTest(endpoint=endpoint):
                def fail(values):
                    values['statuses'] = {endpoint: status}
                result = self.media('media_failure', change=fail)
                self.assertFalse(result['scene']['released'])
                self.assertTrue(result['scene']['cleanupPending'])
                self.assertFalse(result['scene']['loading'])
                self.assertTrue(result['scene']['observing'])
                self.assertFalse(any('/api/v2/playback/start' in q['url'] for q in result['requests']))
                self.assertFalse(result['scene']['attempt']['resumeConsumed'])

    def test_late_exact_active_owner_after_first_empty_is_drained_before_logout(self):
        def late(values):
            values['sessionSequence'] = [[], [{'Id': 'play-fixture'}], []]
        result = self.media('media_unknown', change=late)
        self.assertTrue(result['scene']['released'])
        self.assertTrue(result['results'][-1]['credentialRevoked'])
        self.assertEqual(1, sum(q['url'].endswith('/Sessions/Playing/Stopped') for q in result['requests']))

    def test_explicit_retry_has_new_close_id_and_keeps_the_original_holder(self):
        def fail_once(values):
            values['statuses'] = {'compat/stopped': 503}
        result = self.media('media_retry', change=fail_once)
        self.assertTrue(result['scene']['released'])
        self.assertNotEqual(result['scene']['retryBefore'], result['scene']['retryAfter'])
        self.assertEqual(1, result['scene']['holderCount'])
        self.assertEqual(2, sum(q['url'].endswith('/Sessions/Playing/Stopped') for q in result['requests']))

    def test_local_stop_deadline_keeps_authority_and_ends_spinner(self):
        result = self.media('media_local_timeout')
        self.assertFalse(result['scene']['released'])
        self.assertTrue(result['scene']['cleanupPending'])
        self.assertFalse(result['scene']['loading'])
        self.assertTrue(result['scene']['observing'])
        self.assertFalse(any('/Sessions/Logout' in q['url'] for q in result['requests']))

    def test_profile_change_during_first_report_cannot_confirm_or_report_new_progress(self):
        result = self.media('media_close', scope_change_at='compat/playing')
        playing = [r for r in result['results'] if r['phase'] == 'playing']
        self.assertFalse(playing[0]['ok'])
        self.assertNotEqual(True, playing[0].get('activeConfirmed'))
        self.assertFalse(any(q['url'].endswith('/Sessions/Playing/Progress') for q in result['requests']))
        self.assertTrue(result['results'][-1]['credentialRevoked'])


    def test_buffering_before_first_playing_keeps_existing_startup_allowance(self):
        result = self.media('media_startup')
        self.assertEqual(('playing', 'play'), (result['scene']['startupPhase'], result['scene']['nativeControl']))
        self.assertFalse(any('/Sessions/Logout' in q['url'] for q in result['requests']))

    def test_paused_reanchor_waits_for_landing_then_async_pause_ack_unmutes(self):
        result = self.media('media_seek')
        self.assertEqual('play', result['scene']['beforeLandingControl'])
        self.assertFalse(result['scene']['restoredMute'])

    def test_natural_finished_after_verified_playback_completes_without_lower_fallback(self):
        result = self.media('media_finished')
        self.assertTrue(result['scene']['watched'])
        self.assertTrue(result['scene']['released'])
        self.assertFalse(any('/api/v2/playback/start' in q['url'] for q in result['requests']))
        self.assertFalse(result['scene']['attempt']['resumeConsumed'])

    def test_retry_after_acknowledged_logout_only_retries_remaining_revocation_proof(self):
        def failed_probe(values):
            values['statuses'] = {'compat/revocation': 503}
        result = self.media('media_retry_probe', change=failed_probe)
        self.assertTrue(result['scene']['released'])
        self.assertEqual(1, sum(q['url'].endswith('/Sessions/Playing/Stopped') for q in result['requests']))
        self.assertEqual(1, sum(q['url'].endswith('/Sessions/Logout') for q in result['requests']))
        self.assertTrue(result['results'][-1]['credentialRevoked'])


    def test_changed_fresh_source_on_seek_declines_without_switching_lane_or_native_resume(self):
        def changed(values):
            detail = copy.deepcopy(values['detail'])
            detail['versions'][0]['audio_tracks'][0].update(codec='aac', channels=2)
            detail['versions'][0]['codec_audio'] = 'aac'
            values['reanchorDetail'] = detail
        result = self.media('media_changed_source', change=changed)
        self.assertEqual(1, sum(q['url'].endswith('/PlaybackInfo') for q in result['requests']))
        self.assertTrue(result['scene']['released'])
        self.assertFalse(result['scene']['attempt']['resumeConsumed'])
        self.assertTrue(result['scene']['failureDialog'])


    def test_replaced_finished_cannot_reuse_old_landed_end_proof(self):
        result = self.media('media_replaced_finished')
        self.assertEqual('play', result['scene']['nativeControl'])
        self.assertTrue(result['scene']['bound'])
        self.assertFalse(result['scene']['watched'])


    def test_failed_resumed_native_stop_explains_why_fresh_play_is_blocked(self):
        result = self.media('media_native_stopfailure')
        self.assertEqual(0, result['scene']['blockedStartDelta'])
        self.assertTrue(result['scene']['failureDialog'])
        self.assertIn('cleanup', result['scene']['failureMessage'].lower())
        self.assertIn('restart', result['scene']['failureMessage'].lower())


    def test_next_foreground_intent_waits_for_exact_holder_close(self):
        result = self.media('media_next')
        self.assertEqual(0, result['scene']['nextBeforeTerminal'])
        self.assertIsNotNone(result['scene']['nextJob'], 'actual PlayerAdvance must retain next until exact close')
        self.assertEqual('next-item', result['scene']['nextJob']['params']['itemId'])
        self.assertTrue(result['scene']['released'])
        self.assertTrue(result['results'][-1]['credentialRevoked'])

    def test_shuffle_next_waits_for_exact_holder_close(self):
        result = self.media('media_shuffle_next')
        self.assertEqual(0, result['scene']['nextBeforeTerminal'])
        self.assertIsNotNone(result['scene']['nextJob'])
        self.assertEqual('next-item', result['scene']['nextJob']['params']['itemId'])
        self.assertTrue(result['scene']['released'])
        self.assertTrue(result['results'][-1]['credentialRevoked'])

    def test_old_generation_binding_cannot_replace_reanchored_content(self):
        result = self.media('media_oldgen')
        self.assertTrue(result['scene']['oldGenerationPreserved'])
        self.assertEqual(2, result['scene']['plan']['planGeneration'])
        self.assertEqual(2, len([q for q in result['requests'] if '/PlaybackInfo' in q['url']]))

    def test_preparation_ui_deadline_retains_unresolved_holder_without_fallback(self):
        result = self.media('media_prepare_timeout')
        self.assertEqual('cleanup_pending', result['scene']['phase'])
        self.assertFalse(result['scene']['loading'])
        self.assertTrue(result['scene']['retained'])
        self.assertTrue(result['scene']['observing'])
        self.assertTrue(result['scene']['cancelled'])
        self.assertTrue(result['scene']['cleanupPending'])
        self.assertEqual([], result['requests'])

    def test_active_signout_keeps_transition_until_exact_owned_cleanup(self):
        def fail_logout(values):
            values['statuses'] = {'compat/logout': 503}
        result = self.media('media_transition', change=fail_logout)
        self.assertTrue(result['scene']['transitionHeld'])
        self.assertTrue(result['scene']['retainedWhileCancelled'])
        self.assertTrue(result['scene']['cleanupPending'])
        self.assertFalse(result['scene']['released'])
        self.assertEqual(1, len([q for q in result['requests'] if '/Sessions/Playing/Stopped' in q['url']]))
        self.assertFalse(any('/api/v2/playback/start' in q['url'] for q in result['requests']))

    def test_missing_compatibility_before_auth_can_resume_one_fresh_native_version(self):
        def unavailable(values):
            values['statuses'] = {'native/discovery': 404}
        result = self.media('media_noauth', change=unavailable)
        starts = [q for q in result['requests'] if '/api/v2/playback/start' in q['url']]
        self.assertEqual(1, len(starts))
        self.assertEqual('732', json.loads(starts[0]['body'])['file_id'])
        self.assertTrue(result['scene']['released'])
        self.assertEqual('silo', result['scene']['plan']['provider'])
        self.assertFalse(any('/QuickConnect' in q['url'] or '/Sessions/Logout' in q['url'] for q in result['requests']))

    def test_seek_waits_for_old_media_cleanup_before_new_playback_info(self):
        def fail_stop(values):
            values['statuses'] = {'compat/stopped': 503}
        result = self.media('media_seek', change=fail_stop)
        self.assertEqual(1, len([q for q in result['requests'] if '/PlaybackInfo' in q['url']]))
        self.assertTrue(result['scene']['cleanupPending'])
        self.assertFalse(result['scene']['released'])
        self.assertFalse(any('/api/v2/playback/start' in q['url'] for q in result['requests']))

    def test_back_during_reanchor_http_drains_already_retired_generation(self):
        result = self.media('media_seek_back')
        self.assertTrue(result['scene']['retainedWhileCancelled'])
        self.assertTrue(result['scene']['released'])
        self.assertTrue(result['results'][-1]['credentialRevoked'])
        self.assertFalse(result['scene']['bound'])
        self.assertFalse(any('/api/v2/playback/start' in q['url'] for q in result['requests']))

    def test_late_local_stop_retry_preserves_captured_source_position(self):
        result = self.media('media_local_timeout_retry')
        stopped = [q for q in result['requests'] if '/Sessions/Playing/Stopped' in q['url']]
        self.assertEqual(1, len(stopped))
        report = json.loads(stopped[0]['body'])
        self.assertEqual(300000000, report['PositionTicks'])
        self.assertTrue(report['IsPaused'])
        self.assertTrue(result['scene']['released'])

    def test_profile_switch_during_reanchor_keeps_cleanup_retry_authority(self):
        def fail_logout(values):
            values['statuses'] = {'compat/logout': 503}
        result = self.media('media_seek_profile', change=fail_logout)
        self.assertTrue(result['scene']['retainedWhileCancelled'])
        self.assertTrue(result['scene']['transitionHeld'])
        self.assertTrue(result['scene']['cleanupPending'])
        self.assertFalse(result['scene']['released'])
        self.assertFalse(result['scene']['bound'])
        self.assertTrue(result['results'][-1]['cleanupUnconfirmed'])
        self.assertFalse(any('/api/v2/playback/start' in q['url'] for q in result['requests']))


if __name__ == '__main__':
    unittest.main()
