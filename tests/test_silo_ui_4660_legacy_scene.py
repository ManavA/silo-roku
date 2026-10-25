"""Synthetic 4660 Task/Scene integration, not physical-device acceptance.

Reuses existing HTTP/device/SG seams. Real PlayerInit/PlayItem, Task request and
receipt policy, allocation callback, Video binding, Back and Stop callback run.
Full Scene boot/rendering, actual HTTP and native decoding remain outside scope.
"""
import copy
import json
import unittest
from unittest.mock import patch

from tests import test_silo_ui_native_hdr10_scene as scene_bridge
from tests import test_silo_compat_continuation as task_bridge
from tests import test_silo_delivery_capabilities as delivery


class Legacy4660Scene(unittest.TestCase):
    def task(self, job, *, stop_status=200):
        actual_job = task_bridge.CompatContinuation.job

        def dispatch(instance, **kwargs):
            kwargs['scope'] = job
            replies = kwargs['http']

            def http(responses):
                replies(responses)
                if job['action'] == 'playback_stop':
                    responses[:] = [dict(statusCode=stop_status, body='{"outcome":"stopped"}')]
            kwargs['http'] = http
            return actual_job(instance, **kwargs)

        with patch.object(task_bridge.CompatContinuation, 'job', dispatch):
            return delivery.IndependentDeliveryCapabilities().start()

    def scene(self, *args, **kwargs):
        sdk = scene_bridge.SDK.replace('return "C000X"', 'return "4660X"').replace('return "TV"', 'return "STB"').replace('ModelNumber:"C208X"', 'ModelNumber:"4660X"').replace('return "2160p60"', 'return "1080p"')
        with patch.object(scene_bridge, 'SDK', sdk):
            return scene_bridge.OrdinaryNativeHdr10Scene().scene(*args, **kwargs)

    def test_legacy_h264_aac_cold_bind_back_and_owned_stop_drain(self):
        entry = self.scene()
        self.assertEqual(dict(clock=True, start=0, upNextDismissed=False, introDismissed=False), entry['initialized'])
        self.assertEqual(['detail'], [x['job']['action'] for x in entry['tasks']])
        detail = self.task(entry['tasks'][0]['job'])['outcome']
        self.assertTrue(detail['ok'], detail)
        selected = self.scene([detail])
        start_job = selected['tasks'][1]['job']
        self.assertEqual('playback_start', start_job['action'])
        started = self.task(start_job)
        outcome = started['outcome']
        self.assertTrue(outcome['ok'], outcome)
        self.assertNotIn('compatContinuation', outcome)
        self.assertFalse(started['originalFlag'])
        self.assertFalse(started['p8Flag'])
        posts = [r for r in started['requests'] if r['method'] == 'POST']
        self.assertEqual(1, len(posts))
        request = json.loads(posts[0]['body'])
        self.assertEqual('732', request['file_id'])
        deliveries = request['client_playback_context']['deliveries']
        self.assertFalse(deliveries['original_http']['enabled'])
        hls = deliveries['hls']
        self.assertTrue(hls['enabled'])
        self.assertEqual((['h264'], ['aac'], []), (hls['video_codecs'], hls['audio_decode_codecs'], hls['audio_passthrough_codecs']))
        self.assertNotIn('hdr_details', hls)
        self.assertFalse(any(r['method'] == 'DELETE' for r in started['requests']))
        closed = self.scene([detail, outcome], close=True)
        self.assertEqual((True, 'play', 'hls'), (closed['bound'], closed['boundControl'], closed['boundFormat']))
        self.assertEqual(('search', True, 'stop'), (closed['view'], closed['detached'], closed['control']))
        self.assertEqual(['detail', 'playback_start', 'playback_stop'], [t['job']['action'] for t in closed['tasks']])
        stop = closed['tasks'][-1]
        self.assertEqual('stop', stop['nativeControl'])
        self.assertEqual(1, closed['pending'])
        plan = outcome['plan']
        self.assertEqual((plan['sessionId'], plan['installationId'], 42000, 1, False), tuple(stop['job']['params'][k] for k in ('sessionId', 'installationId', 'positionMs', 'sequence', 'isPaused')))
        self.assertEqual({k: start_job[k] for k in ('provider', 'sourceId', 'profileId', 'generation')}, {k: stop['job'][k] for k in ('provider', 'sourceId', 'profileId', 'generation')})
        stopped = self.task(stop['job'])
        self.assertTrue(stopped['outcome']['ok'], stopped['outcome'])
        self.assertEqual((stop['job']['requestId'], 0), (stopped['outcome']['requestId'], stopped['outcome']['sessionRevision']))
        deletes = [r for r in stopped['requests'] if r['method'] == 'DELETE']
        self.assertEqual(1, len(deletes))
        self.assertTrue(deletes[0]['url'].endswith('/playback/' + plan['sessionId']))
        body = json.loads(deletes[0]['body'])
        self.assertEqual(plan['installationId'], body['installation_id'])
        self.assertEqual('10000000-0000-4000-8000-000000000001', body['stop_id'])
        self.assertEqual((42, 1, False), (body['position'], body['sequence'], body['is_paused']))
        stale = copy.deepcopy(stopped['outcome'])
        stale['requestId'] += 100
        awaiting = self.scene([detail, outcome], close=True, stop_outcome=stale)
        self.assertEqual((1, True, 'stop'), (awaiting['pending'], awaiting['detached'], awaiting['control']))
        drained = self.scene([detail, outcome], close=True, stop_outcome=stopped['outcome'])
        self.assertEqual((0, 0, True, 'stop'), (drained['pending'], drained['tickets'], drained['detached'], drained['control']))
