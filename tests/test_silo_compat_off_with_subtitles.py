"""Source-derived explicit Off DTO with real subtitle streams; synthetic identities."""
import json
import unittest
from tests import test_silo_compat_playback_task as task


def off_subtitles(values):
    metadata=values['metadata']['MediaSources'][0]
    metadata['DefaultSubtitleStreamIndex']=3
    metadata['MediaStreams'].append(dict(Index=3,Type='Subtitle',Codec='subrip',IsDefault=True,IsForced=True))
    playback=values['playback']['MediaSources'][0]
    playback.pop('DefaultSubtitleStreamIndex')
    playback['MediaStreams'].append(dict(Index=3,Type='Subtitle',Codec='subrip',IsDefault=False,IsForced=True))


class CompatOffWithSubtitles(unittest.TestCase):
    def test_source_default_forced_subtitle_can_be_explicitly_off_after_post(self):
        result=task.CompatPlaybackTask().transcript(change=off_subtitles)
        self.assertEqual(['prepared','closed'],[x['phase'] for x in result['results']],result['results'])
        self.assertTrue(all(x['ok'] for x in result['results']))
        request=next(q for q in result['requests'] if '/PlaybackInfo' in q['url'])
        body=json.loads(request['body'])
        self.assertEqual((-1,2,task.SOURCE),(body['SubtitleStreamIndex'],body['AudioStreamIndex'],body['MediaSourceId']))
        self.assertEqual(0,result['mediaRequests'])
        self.assertTrue(result['results'][-1]['credentialRevoked'])
        self.assertTrue(result['privateCleared'])
        self.assertEqual(1,sum('/Sessions/Logout' in q['url'] for q in result['requests']))

    def test_explicit_off_with_subtitles_binds_seeks_and_closes_actual_owned_scene(self):
        from tests import test_silo_single_source_compat_flow as flow
        result=flow.SingleSourceCompatFlow().scene(control='media_roundtrip',change=off_subtitles)
        self.assertTrue(result['scene']['released'])
        self.assertFalse(result['scene']['bound'])
        self.assertFalse(result['scene']['failureDialog'])
        self.assertEqual({1,2,3},{x['planGeneration'] for x in result['results'] if x['phase']=='playing' and x.get('activeConfirmed') is True})
        self.assertTrue(result['results'][-1]['credentialRevoked'])
        self.assertTrue(result['results'][-1]['mediaClosed'])
        self.assertFalse(result['results'][-1]['cleanupUnconfirmed'])
        posts=[q for q in result['requests'] if '/PlaybackInfo' in q['url']]
        self.assertEqual(3,len(posts))
        self.assertTrue(all(json.loads(q['body'])['SubtitleStreamIndex']==-1 for q in posts))
        self.assertEqual(3,sum('/Sessions/Playing/Stopped' in q['url'] for q in result['requests']))
        self.assertEqual(3,sum('/Videos/ActiveEncodings?' in q['url'] for q in result['requests']))
        self.assertEqual(1,sum('/Sessions/Logout' in q['url'] for q in result['requests']))
        self.assertFalse(any('/playback/start' in q['url'] for q in result['requests']))

    def test_each_receipt_subtitle_must_be_typed_false_even_with_explicit_minus_one(self):
        from tests import test_silo_compat_playback_policy as policy
        boundary=policy.CompatPlaybackPolicy()
        for explicit in (False,True):
            wire,proof=boundary.fixture();proof['subtitleMode']='off';source=wire['MediaSources'][0]
            if not explicit:source.pop('DefaultSubtitleStreamIndex')
            source['MediaStreams'].extend([dict(Index=3,Type='Subtitle',Codec='subrip',IsDefault=False,IsForced=True),
                                          dict(Index=4,Type='Subtitle',Codec='ass',IsDefault=False,IsForced=False)])
            self.assertIsNotNone(boundary.receipt(wire,proof))
            for value in ('missing',True,None,'false',0):
                with self.subTest(explicit=explicit,default=value):
                    stream=source['MediaStreams'][-1]
                    if value=='missing':stream.pop('IsDefault',None)
                    else:stream['IsDefault']=value
                    self.assertIsNone(boundary.receipt(wire,proof))

    def test_missing_true_null_or_string_defaults_refuse_and_revoke_unused_credential(self):
        for default in ('missing',True,None,'false'):
            def bad(values):
                off_subtitles(values)
                stream=values['playback']['MediaSources'][0]['MediaStreams'][-1]
                if default=='missing':stream.pop('IsDefault')
                else:stream['IsDefault']=default
            with self.subTest(default=default):
                result=task.CompatPlaybackTask().transcript(change=bad)
                last=result['results'][-1]
                self.assertEqual('unsafe_recipe',last['errorCode'])
                self.assertTrue(last['credentialRevoked'])
                self.assertTrue(last['mediaNeverRequested'])
                self.assertFalse(last['cleanupUnconfirmed'])
                self.assertEqual(0,result['mediaRequests'])
                self.assertTrue(result['privateCleared'])
                self.assertFalse(any(x['phase'] in ('prepared','binding','playing') for x in result['results']))
                self.assertEqual(1,sum('/Sessions/Logout' in q['url'] for q in result['requests']))
                self.assertEqual(('GET','https://compat.example/media/Sessions'),(result['requests'][-1]['method'],result['requests'][-1]['url']))
                self.assertFalse(any(q['method']=='DELETE' for q in result['requests']))
