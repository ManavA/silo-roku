"""Source-derived Go DTO omission, through actual persistent Task/HTTP boundaries.

Synthetic fixture identities; this is not a captured native PlaybackInfo response.
Official effectiveCompatSubtitleStreamIndex returns nil for selected -1, and the
pointer DTO's omitempty tag omits DefaultSubtitleStreamIndex on the wire.
"""
import json
import unittest
from tests import test_silo_compat_playback_task as task


def omitted_off_default(values):
    for name in ('metadata','playback'):
        values[name]['MediaSources'][0].pop('DefaultSubtitleStreamIndex')


class CompatSubtitleOff(unittest.TestCase):
    def test_off_request_accepts_omitted_default_without_allocating_media(self):
        result=task.CompatPlaybackTask().transcript(change=omitted_off_default)
        self.assertEqual(['prepared','closed'],[x['phase'] for x in result['results']],result['results'])
        self.assertTrue(all(x['ok'] for x in result['results']),result['results'])
        request=next(q for q in result['requests'] if '/PlaybackInfo' in q['url'])
        body=json.loads(request['body'])
        self.assertEqual(-1,body['SubtitleStreamIndex'])
        self.assertEqual(task.SOURCE,body['MediaSourceId'])
        self.assertEqual(2,body['AudioStreamIndex'])
        self.assertEqual(0,result['mediaRequests'])
        self.assertTrue(result['results'][-1]['credentialRevoked'])
        self.assertTrue(result['privateCleared'])
        self.assertEqual(1,sum('/Sessions/Logout' in q['url'] for q in result['requests']))
        self.assertFalse(any(q['method']=='DELETE' for q in result['requests']))

    def test_omitted_off_default_survives_real_scene_bind_seek_and_owned_close(self):
        from tests import test_silo_single_source_compat_flow as flow
        result=flow.SingleSourceCompatFlow().scene(control='media_roundtrip',change=omitted_off_default)
        self.assertTrue(result['scene']['released'])
        self.assertFalse(result['scene']['bound'])
        playing=[x for x in result['results'] if x['phase']=='playing' and x.get('activeConfirmed') is True]
        self.assertEqual({1,2,3},{x['planGeneration'] for x in playing})
        self.assertEqual('closed',result['results'][-1]['phase'])
        self.assertTrue(result['results'][-1]['credentialRevoked'])
        self.assertTrue(result['results'][-1]['mediaClosed'])
        self.assertFalse(result['results'][-1]['cleanupUnconfirmed'])
        playback=[q for q in result['requests'] if '/PlaybackInfo' in q['url']]
        self.assertEqual(3,len(playback))
        self.assertTrue(all(json.loads(q['body'])['SubtitleStreamIndex']==-1 for q in playback))
        self.assertEqual(3,sum('/Sessions/Playing/Stopped' in q['url'] for q in result['requests']))
        self.assertEqual(3,sum('/Videos/ActiveEncodings?' in q['url'] for q in result['requests']))
        self.assertEqual(1,sum('/Sessions/Logout' in q['url'] for q in result['requests']))
        self.assertFalse(any('/playback/start' in q['url'] for q in result['requests']))

    def test_omission_requires_retained_off_and_typed_deselection_and_present_values_stay_strict(self):
        from tests import test_silo_compat_playback_policy as policy
        boundary=policy.CompatPlaybackPolicy()
        def inputs():
            wire,proof=boundary.fixture();proof['subtitleMode']='off'
            return wire,proof
        wire,proof=inputs();wire['MediaSources'][0].pop('DefaultSubtitleStreamIndex')
        self.assertIsNotNone(boundary.receipt(wire,proof))
        for mode in (None,'auto','on',False):
            with self.subTest(mode=mode):
                changed=dict(proof)
                if mode is None:changed.pop('subtitleMode')
                else:changed['subtitleMode']=mode
                self.assertIsNone(boundary.receipt(wire,changed))
        wire['MediaSources'][0]['MediaStreams'].append(dict(Index=3,Type='Subtitle',Codec='subrip'))
        self.assertIsNone(boundary.receipt(wire,proof))
        # Explicit numeric -1 also requires typed deselection on every subtitle.
        wire['MediaSources'][0]['MediaStreams'][-1]['IsDefault']=False
        wire['MediaSources'][0]['DefaultSubtitleStreamIndex']=-1
        self.assertIsNotNone(boundary.receipt(wire,proof))
        for value in (None,True,False,'-1',0,3):
            with self.subTest(default=value):
                wire['MediaSources'][0]['DefaultSubtitleStreamIndex']=value
                self.assertIsNone(boundary.receipt(wire,proof))

    def test_contradictory_omitted_default_refuses_but_revokes_exact_unused_credential(self):
        def subtitle_present(values):
            omitted_off_default(values)
            values['playback']['MediaSources'][0]['MediaStreams'].append(dict(Index=3,Type='Subtitle',Codec='subrip'))
        result=task.CompatPlaybackTask().transcript(change=subtitle_present)
        self.assertEqual('unsafe_recipe',result['results'][-1]['errorCode'])
        self.assertTrue(result['results'][-1]['credentialRevoked'])
        self.assertTrue(result['results'][-1]['mediaNeverRequested'])
        self.assertFalse(result['results'][-1]['cleanupUnconfirmed'])
        self.assertEqual(0,result['mediaRequests'])
        self.assertTrue(result['privateCleared'])
        self.assertEqual(1,sum('/Sessions/Logout' in q['url'] for q in result['requests']))
        self.assertEqual(('GET','https://compat.example/media/Sessions'),
                         (result['requests'][-1]['method'],result['requests'][-1]['url']))
        self.assertEqual('Bearer '+task.TOKEN,result['requests'][-1]['headers']['Authorization'])
        self.assertFalse(any(q['method']=='DELETE' for q in result['requests']))
