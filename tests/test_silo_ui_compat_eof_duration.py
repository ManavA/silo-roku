"""Actual Scene EOF callback uses its selected owned source, not catalog metadata."""
import json
import unittest
from tests import test_silo_single_source_compat_flow as flow


class CompatEOFDuration(unittest.TestCase):
    def scene(self,catalog=0,position=59.5,event="finished",native_refusal=False):
        def source(envelope,wire):
            wire['versions'][0]['duration']=60
        sdk={
            'title:"Fixture",durationMs:7200000}':'title:"Fixture",durationMs:'+str(catalog)+'}',
            'm.video.position=7199.5:onPlayerPosition()':'m.video.position='+str(position)+':onPlayerPosition()',
        }
        if event=='error':
            sdk['m.video.state="finished":onVideoState():m.video.state="stopped"']='m.video.state="error":onVideoState():m.video.state="stopped"'
        def refuse_native(values):
            # A 503 has no typed terminal retry authority or allocated lease.
            values['nativeplan']={}
            values.setdefault('statuses',{})['native/start']=503
        return flow.SingleSourceCompatFlow().scene(control='media_finished',mutate=source,sdk_overrides=sdk,change=refuse_native if native_refusal else None)

    def test_zero_catalog_duration_finishes_using_selected_owned_sixty_second_version(self):
        result=self.scene()
        self.assertTrue(result['scene']['watched'])
        self.assertTrue(result['scene']['released'])
        self.assertFalse(result['scene']['bound'])
        self.assertFalse(result['scene']['failureDialog'])
        self.assertTrue(result['results'][-1]['mediaClosed'])
        self.assertTrue(result['results'][-1]['credentialRevoked'])
        self.assertFalse(result['results'][-1]['cleanupUnconfirmed'])
        self.assertFalse(any('/playback/start' in q['url'] for q in result['requests']))

    def test_selected_source_duration_takes_precedence_over_long_catalog_duration(self):
        result=self.scene(catalog=7200000)
        self.assertTrue(result['scene']['watched'])
        self.assertTrue(result['scene']['released'])
        self.assertFalse(result['scene']['failureDialog'])

    def test_early_finish_and_actual_error_remain_failures_despite_short_catalog_duration(self):
        for position,event in [(42.0,'finished'),(59.5,'error')]:
            with self.subTest(position=position,event=event):
                result=self.scene(catalog=10000,position=position,event=event,native_refusal=True)
                self.assertFalse(result['scene']['watched'])
                self.assertTrue(result['scene']['released'])
                self.assertTrue(result['scene']['failureDialog'])
                closed=[r for r in result['results'] if r.get('phase')=='closed']
                self.assertEqual(1,len(closed))
                self.assertTrue(closed[0]['mediaClosed'])
                self.assertTrue(closed[0]['credentialRevoked'])
                self.assertFalse(closed[0]['cleanupUnconfirmed'])
                requests=result['requests']
                starts=[q for q in requests if '/playback/start' in q['url']]
                self.assertEqual(['731'],[json.loads(q['body'])['file_id'] for q in starts])
                self.assertLess(next(i for i,q in enumerate(requests) if '/Sessions/Logout' in q['url']),requests.index(starts[0]))
                self.assertEqual(1,result['scene']['holderCount'])
                self.assertTrue(result['scene']['attempt']['resumeConsumed'])
                self.assertEqual(1,sum('/PlaybackInfo' in q['url'] for q in requests))
                self.assertEqual(1,len(result['scene']['nativeResults']))
                self.assertFalse(result['scene']['nativeResults'][0]['ok'])
                self.assertEqual('server_error',result['scene']['nativeResults'][0]['errorCode'])
                self.assertEqual([],result['scene']['resumeJobs'])

    def test_invalid_selected_source_is_rejected_at_admission_before_any_eof(self):
        # Invalid durations/identity cannot reach a valid current EOF state;
        # exercise their real admission boundary rather than forge retained state.
        for change in ('unknown','malformed','mismatched_file'):
            def source(envelope,wire):
                version=wire['versions'][0]
                if change=='unknown':version.pop('duration')
                elif change=='malformed':version['duration']='not-a-duration'
                else:version['file_id']='733'
            with self.subTest(change=change):
                result=flow.SingleSourceCompatFlow().scene(control='media_finished',mutate=source)
                self.assertFalse(result['scene']['holderCreated'])
                self.assertEqual([],result['results'])
                self.assertFalse(any('/PlaybackInfo' in q['url'] for q in result['requests']))
