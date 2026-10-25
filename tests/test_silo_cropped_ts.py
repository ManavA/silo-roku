"""Cropped P8 compatibility selection and receipt validation."""
import copy
import json
import unittest
from tests import test_silo_modern_compat_policy as policy
from tests import test_silo_modern_compat_flow as flow
from tests import test_silo_compat_continuation as producer
from tests import test_silo_compat_playback_task as holder


def cropped(wire, decision):
    del wire['versions'][1:]
    wire['versions'][0]['video_tracks'][0].update(width=3834, height=1602)


class CroppedTSCompatibility(unittest.TestCase):
    def test_cropped_source_reaches_real_producer_scene_and_owned_ts_holder(self):
        result = producer.CompatContinuation().job(enabled=None, p7_enabled=None,
            automatic_hdr10=None, device=flow.modern_device(), mutate=cropped)
        self.assertEqual('compat_prepare_required', result['outcome'].get('errorCode'), result['outcome'])
        self.assertEqual(flow.KIND, result['outcome']['compatContinuation']['eligibilityKind'])
        self.assertFalse(any('/playback/start' in q['url'] for q in result['requests']))
        _, wire, decision = producer.CompatContinuation().fixture()
        cropped(wire, decision)
        scene = dict(envelope=result['outcome'], wire=wire, control='media_close')
        played = holder.CompatPlaybackTask().transcript(scene=scene, device_overrides=flow.modern_device())
        self.assertTrue(played['scene']['holderCreated'])
        self.assertTrue(played['scene']['released'])
        self.assertTrue(played['results'][-1]['credentialRevoked'])
        request = next(json.loads(q['body']) for q in played['requests'] if '/PlaybackInfo' in q['url'])
        conditions = request['DeviceProfile']['CodecProfiles'][0]['Conditions']
        self.assertEqual(['3834', '1602'], [c['Value'] for c in conditions])
        self.assertEqual(-1, request['SubtitleStreamIndex'])
        self.assertEqual(1, sum('/Sessions/Playing/Stopped' in q['url'] for q in played['requests']))

    def test_manual_cropped_version_keeps_selected_file_through_owned_holder(self):
        result = producer.CompatContinuation().job(enabled=None, p7_enabled=None,
            automatic_hdr10=None, device=flow.modern_device(), mutate=mixed_versions,
            options={'autoVersion': False})
        self.assertEqual('compat_prepare_required', result['outcome'].get('errorCode'), result['outcome'])
        continuation = result['outcome']['compatContinuation']
        self.assertFalse(continuation['autoVersion'])
        self.assertEqual({'requestedFileId': '731'}, continuation['manualVersionSelection'])
        self.assertEqual(('731', '731'), (continuation['fileId'], continuation['nativeSelectedFileId']))
        _, wire, decision = producer.CompatContinuation().fixture()
        mixed_versions(wire, decision)
        scene = dict(envelope=result['outcome'], wire=wire, control='media_close', manualFileId='731')
        played = holder.CompatPlaybackTask().transcript(scene=scene, device_overrides=flow.modern_device())
        self.assertTrue(played['scene']['holderCreated'])
        self.assertTrue(played['scene']['released'])
        self.assertTrue(played['results'][-1]['credentialRevoked'])
        self.assertFalse(any('/playback/start' in q['url'] for q in result['requests'] + played['requests']))

    def test_explicit_nondefault_audio_reaches_owned_holder(self):
        result = producer.CompatContinuation().job(enabled=None, p7_enabled=None,
            automatic_hdr10=None, device=flow.modern_device(), mutate=wire_indexed_tracks,
            options={'autoVersion': False, 'audioTrackId': 'file:731:audio:1', 'audioTrackIndex': 1})
        self.assertEqual('compat_prepare_required', result['outcome'].get('errorCode'), result['outcome'])
        selection = result['outcome']['compatContinuation']['manualVersionSelection']['explicitAudioSelection']
        self.assertEqual(('file:731:audio:1', 1, '19', 19),
            (selection['id'], selection['index'], selection['track']['id'], selection['track']['wireIndex']))
        _, wire, decision = producer.CompatContinuation().fixture()
        wire_indexed_tracks(wire, decision)
        scene = dict(envelope=result['outcome'], wire=wire, control='media_close',
            manualFileId='731', audioOrdinal=1, audioOnly=True)
        played = holder.CompatPlaybackTask().transcript(scene=scene, device_overrides=flow.modern_device())
        self.assertTrue(played['scene']['holderCreated'])
        self.assertTrue(played['scene']['released'])
        request = next(json.loads(q['body']) for q in played['requests'] if '/PlaybackInfo' in q['url'])
        self.assertEqual(2, request['AudioStreamIndex'])
        self.assertTrue(played['results'][-1]['credentialRevoked'])

    def test_explicit_default_audio_failure_keeps_manual_file(self):
        envelope = producer.CompatContinuation().job(enabled=None, p7_enabled=None,
            automatic_hdr10=None, device=flow.modern_device(), mutate=explicit_tracks,
            options={'autoVersion': False, 'audioTrackId': 'file:731:audio:0', 'audioTrackIndex': 0})['outcome']
        self.assertEqual('compat_prepare_required', envelope.get('errorCode'))
        _, wire, decision = producer.CompatContinuation().fixture()
        explicit_tracks(wire, decision)
        played = holder.CompatPlaybackTask().transcript(scene=dict(envelope=envelope,
            wire=wire, control='media_failure', manualFileId='731', audioOrdinal=0),
            device_overrides=flow.modern_device())
        self.assertTrue(played['scene']['holderCreated'])
        self.assertTrue(played['scene']['released'])
        self.assertEqual([], played['scene']['resumeJobs'])
        self.assertTrue(played['scene']['failureDialog'])

    def test_explicit_audio_rejects_bad_identity_and_unsupported_track(self):
        for choice in ({'audioTrackId': 'file:732:audio:1', 'audioTrackIndex': 1},
                       {'audioTrackId': 'file:731:audio:0', 'audioTrackIndex': 1},
                       {'audioTrackId': 'file:731:audio:1'},
                       {'audioTrackId': 'file:731:audio:9', 'audioTrackIndex': 9}):
            with self.subTest(choice=choice):
                result = producer.CompatContinuation().job(enabled=None, p7_enabled=None,
                    automatic_hdr10=None, device=flow.modern_device(), mutate=explicit_tracks,
                    options=dict(autoVersion=False, **choice))
                self.assertNotIn('compatContinuation', result['outcome'])
        def unsupported(wire, decision):
            explicit_tracks(wire, decision)
            wire['versions'][0]['audio_tracks'][1]['codec'] = 'truehd'
        result = producer.CompatContinuation().job(enabled=None, p7_enabled=None,
            automatic_hdr10=None, device=flow.modern_device(), mutate=unsupported,
            options={'autoVersion': False, 'audioTrackId': 'file:731:audio:1', 'audioTrackIndex': 1})
        self.assertNotIn('compatContinuation', result['outcome'])

    def test_explicit_audio_fresh_inventory_and_live_choice_cannot_rebind(self):
        envelope = producer.CompatContinuation().job(enabled=None, p7_enabled=None,
            automatic_hdr10=None, device=flow.modern_device(), mutate=explicit_tracks,
            options={'autoVersion': False, 'audioTrackId': 'file:731:audio:1', 'audioTrackIndex': 1})['outcome']
        _, wire, decision = producer.CompatContinuation().fixture()
        explicit_tracks(wire, decision)
        for drift in ('fresh', 'live', 'marker', 'scope'):
            with self.subTest(drift=drift):
                changed = copy.deepcopy(envelope)
                if drift == 'marker':
                    changed['compatContinuation']['manualVersionSelection']['explicitAudioSelection']['index'] = 0
                def change(values):
                    if drift == 'fresh':
                        values['detail']['versions'][0]['audio_tracks'][1]['channels'] = 2
                played = holder.CompatPlaybackTask().transcript(scene=dict(envelope=changed,
                    wire=wire, control='media_close', manualFileId='731', audioOnly=True,
                    audioOrdinal=0 if drift == 'live' else 1, staleAudio=drift == 'scope'), change=change,
                    device_overrides=flow.modern_device())
                self.assertFalse(any('/PlaybackInfo' in q['url'] for q in played['requests']))
                self.assertFalse(any(q['url'].endswith('/Sessions/Playing') for q in played['requests']))

    def test_explicit_selected_audio_keeps_native_priority(self):
        def native(wire, decision):
            explicit_tracks(wire, decision)
            wire['versions'][0]['hdr'] = False
            wire['versions'][0]['video_tracks'] = [dict(codec='hevc', profile='main 10', level=150,
                width=3834, height=1602, bit_depth=10, frame_rate='23.976', interlaced=False)]
        result = producer.CompatContinuation().job(enabled=None, p7_enabled=None,
            automatic_hdr10=None, device=flow.modern_device(), mutate=native,
            options={'autoVersion': False, 'audioTrackId': 'file:731:audio:1', 'audioTrackIndex': 1})
        self.assertNotIn('compatContinuation', result['outcome'])
        starts = [json.loads(q['body']) for q in result['requests'] if '/playback/start' in q['url']]
        self.assertEqual(['731'], [q['file_id'] for q in starts])
        self.assertEqual(1, starts[0]['audio_track_index'])

    def test_manual_cropped_rejects_file_mismatch_and_stale_owner(self):
        envelope = producer.CompatContinuation().job(enabled=None, p7_enabled=None,
            automatic_hdr10=None, device=flow.modern_device(), mutate=mixed_versions,
            options={'autoVersion': False})['outcome']
        _, wire, decision = producer.CompatContinuation().fixture()
        mixed_versions(wire, decision)
        for field in ('requestedFileId', 'fileId', 'nativeSelectedFileId', 'marker', 'owner', 'live'):
            with self.subTest(field=field):
                changed = copy.deepcopy(envelope)
                c = changed['compatContinuation']
                if field == 'marker':
                    c['manualVersionSelection']['requestedFileId'] = '732'
                elif field == 'owner':
                    c['owner']['generation'] = 6
                elif field != 'live':
                    c[field] = '732'
                scene = dict(envelope=changed, wire=wire, control='media_close',
                    manualFileId='732' if field == 'live' else '731')
                played = holder.CompatPlaybackTask().transcript(scene=scene,
                    device_overrides=flow.modern_device())
                self.assertFalse(played['scene']['holderCreated'])
                self.assertFalse(any('/compat/' in q['url'] for q in played['requests']))

    def test_manual_cropped_denies_explicit_audio_and_stale_producer(self):
        for options, race in [({'audioTrackId': 'file:731:audio:1', 'audioTrackIndex': 1}, ''),
                              ({}, 'revision'), ({}, 'pin')]:
            with self.subTest(options=options, race=race):
                result = producer.CompatContinuation().job(enabled=None, p7_enabled=None,
                    automatic_hdr10=None, device=flow.modern_device(), mutate=mixed_versions,
                    options=dict(autoVersion=False, **options), race=race)
                self.assertNotIn('compatContinuation', result['outcome'])

    def test_manual_cropped_requires_positive_default_audio_proof(self):
        device = flow.modern_device()
        device['format.codec="eac3"'] = 'format.codec="unsupported-fixture"'
        result = producer.CompatContinuation().job(enabled=None, p7_enabled=None,
            automatic_hdr10=None, device=device, mutate=mixed_versions,
            options={'autoVersion': False})
        self.assertNotIn('compatContinuation', result['outcome'])

    def test_manual_failure_cannot_resume_another_version_as_auto(self):
        envelope = producer.CompatContinuation().job(enabled=None, p7_enabled=None,
            automatic_hdr10=None, device=flow.modern_device(), mutate=mixed_versions,
            options={'autoVersion': False})['outcome']
        _, wire, decision = producer.CompatContinuation().fixture()
        mixed_versions(wire, decision)
        played = holder.CompatPlaybackTask().transcript(
            scene=dict(envelope=envelope, wire=wire, control='media_failure', manualFileId='731'),
            device_overrides=flow.modern_device())
        self.assertTrue(played['scene']['released'])
        self.assertEqual([], played['scene']['resumeJobs'])
        self.assertTrue(played['scene']['failureDialog'])
        self.assertFalse(any('/playback/start' in q['url'] for q in played['requests']))

    def test_manual_supported_selected_file_keeps_native_priority(self):
        def native_selected(wire, decision):
            mixed_versions(wire, decision)
            high = wire['versions'][1]
            high['hdr'] = False
            high['video_tracks'] = [dict(codec='hevc', profile='main 10', level=150,
                width=3834, height=1602, bit_depth=10, frame_rate='23.976', interlaced=False)]
        result = producer.CompatContinuation().job(enabled=None, p7_enabled=None,
            automatic_hdr10=None, device=flow.modern_device(), mutate=native_selected,
            options={'autoVersion': False})
        self.assertNotIn('compatContinuation', result['outcome'])
        starts = [json.loads(q['body']) for q in result['requests'] if '/playback/start' in q['url']]
        self.assertEqual(['731'], [q['file_id'] for q in starts])

    def test_modern_bounds_refuse_missing_malformed_or_oversize_rasters(self):
        seam = policy.ModernCompat()
        cases = []
        for name, value in [('width', 3841), ('height', 2161), ('width', 0),
                            ('height', -1), ('width', '3834'), ('height', True),
                            ('width', None), ('height', []), ('width', 3834.5)]:
            case = seam.data()
            case['detail']['versions'][0]['videoTracks'][0].update(width=3834, height=1602)
            case['detail']['versions'][0]['videoTracks'][0][name] = value
            cases.append(case)
        for name in ('width', 'height'):
            case = seam.data()
            case['detail']['versions'][0]['videoTracks'][0].pop(name)
            cases.append(case)
        self.assertEqual([None] * len(cases), seam.candidates(cases))

    def test_legacy_class_keeps_3840_width_and_modern_proof_retains_actual_raster(self):
        seam = policy.ModernCompat()
        modern = seam.data()
        modern['detail']['versions'][0]['videoTracks'][0].update(width=3834, height=1602)
        legacy = copy.deepcopy(modern)
        legacy['kind'] = None
        legacy['snapshot'].update(model='C000X', modelNumber='C208X', modelType='TV', os='16.0.4.834')
        full = copy.deepcopy(legacy)
        full['detail']['versions'][0]['videoTracks'][0]['width'] = 3840
        proofs = seam.candidates([modern, legacy, full])
        self.assertEqual((3834, 1602), (proofs[0]['video']['width'], proofs[0]['video']['height']))
        self.assertIsNone(proofs[1])
        self.assertIsNotNone(proofs[2])

    def test_cropped_metadata_or_playback_receipt_raster_drift_revokes_without_media(self):
        envelope = producer.CompatContinuation().job(enabled=None, p7_enabled=None,
            automatic_hdr10=None, device=flow.modern_device(), mutate=cropped)['outcome']
        self.assertEqual('compat_prepare_required', envelope.get('errorCode'))
        _, wire, decision = producer.CompatContinuation().fixture()
        cropped(wire, decision)
        for endpoint, field in [('metadata', 'Width'), ('playback', 'Height')]:
            with self.subTest(endpoint=endpoint, field=field):
                def drift(values):
                    values[endpoint]['MediaSources'][0]['MediaStreams'][0][field] += 2
                scene = dict(envelope=envelope, wire=wire, control='media_close')
                result = holder.CompatPlaybackTask().transcript(scene=scene,
                    device_overrides=flow.modern_device(), change=drift)
                self.assertFalse(result['results'][-1]['ok'])
                self.assertTrue(result['results'][-1]['credentialRevoked'])
                self.assertTrue(result['results'][-1]['mediaNeverRequested'])
                self.assertFalse(any(q['url'].endswith('/Sessions/Playing') for q in result['requests']))

    def test_auto_full_inventory_prefers_cropped_ts_over_proven_lower_native(self):
        def crop_only(wire, decision):
            wire['versions'][0]['video_tracks'][0].update(width=3834, height=1602)
        result = producer.CompatContinuation().job(enabled=None, p7_enabled=None,
            automatic_hdr10=None, device=flow.modern_device(), mutate=crop_only)
        self.assertEqual('compat_prepare_required', result['outcome'].get('errorCode'), result['outcome'])
        continuation = result['outcome']['compatContinuation']
        self.assertEqual('native_selection_lower_resolution', continuation['reason'])
        self.assertEqual(('731', '732'), (continuation['fileId'], continuation['nativeSelectedFileId']))
        self.assertEqual(flow.KIND, continuation['eligibilityKind'])
        _, wire, decision = producer.CompatContinuation().fixture()
        crop_only(wire, decision)
        self.assertEqual(2, len(wire['versions']))
        scene = dict(envelope=result['outcome'], wire=wire, control='media_close')
        played = holder.CompatPlaybackTask().transcript(scene=scene, device_overrides=flow.modern_device())
        self.assertTrue(played['scene']['holderCreated'])
        self.assertTrue(played['scene']['released'])
        self.assertTrue(played['results'][-1]['credentialRevoked'])
        self.assertFalse(any('/playback/start' in q['url'] for q in played['requests']))
        request = next(json.loads(q['body']) for q in played['requests'] if '/PlaybackInfo' in q['url'])
        self.assertEqual(['3834', '1602'], [c['Value'] for c in request['DeviceProfile']['CodecProfiles'][0]['Conditions']])


def mixed_versions(wire, decision):
    high, low = wire['versions']
    high.update(bitrate=25560)
    high['video_tracks'][0].update(width=3834, height=1602, frame_rate='23.976')
    high['video_tracks'][0].pop('dv_el_present', None)
    low.update(codec_audio='eac3', bitrate=10264,
        audio_tracks=[dict(codec='eac3', channels=6, default=True, language='en')])
    low['video_tracks'] = [dict(codec='h264', profile='High', level=40,
        width=1920, height=800, bit_depth=8, frame_rate='23.976',
        dv_config_present=False, dv_bl_compat_id_present=False,
        dv_enhancement_layer='none', color_transfer='bt709',
        color_primaries='bt709', color_space='bt709', interlaced=False)]
    wire['versions'][:] = [low, high]


class CroppedVersionSelection(unittest.TestCase):
    def test_sdr_anchor_is_proven_before_cropped_ts_comparison(self):
        result = producer.CompatContinuation().job(enabled=None, p7_enabled=None,
            automatic_hdr10=None, device=flow.modern_device(), mutate=mixed_versions)
        self.assertEqual('compat_prepare_required', result['outcome'].get('errorCode'), result['outcome'])
        continuation = result['outcome']['compatContinuation']
        self.assertEqual('native_selection_lower_resolution', continuation['reason'])
        self.assertEqual(('731', '732'), (continuation['fileId'], continuation['nativeSelectedFileId']))
        self.assertEqual(flow.KIND, continuation['eligibilityKind'])
        self.assertFalse(any('/playback/start' in q['url'] for q in result['requests']))


def explicit_tracks(wire, decision):
    mixed_versions(wire, decision)
    high = wire['versions'][1]
    high['audio_tracks'] = [dict(codec='eac3', language='en', channels=6,
        layout='5.1', default=index == 0) for index in range(2)]
    wire['versions'].remove(high)
    wire['versions'].insert(0, high)


def wire_indexed_tracks(wire, decision):
    explicit_tracks(wire, decision)
    for index, track in enumerate(wire['versions'][0]['audio_tracks']):
        track['index'] = (11, 19)[index]
