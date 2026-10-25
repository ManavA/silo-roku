"""Modern compatibility captions through real playback jobs, holder and Scene."""
import copy
import json
import unittest
from tests import test_silo_modern_compat_flow as modern
from tests import test_silo_compat_playback_task as holder
from tests import test_silo_compat_continuation as native

SRT = '1\n00:00:30,000 --> 00:00:32,000\nCaption'


class CompatEnabledSubtitles(unittest.TestCase):
    def scene(self, control='media_close', server_change=None, scenario=None, empty=False, mode='on'):
        def caption(wire, decision):
            wire['versions'][0]['subtitle_tracks'] = [] if empty else [dict(index=2, codec='subrip', language='en', default=True, forced=False, external=False)]
        outcome = modern.ModernCompatFlow().continuation(options={'subtitleMode': mode}, mutate=caption)['outcome']
        self.assertEqual('compat_prepare_required', outcome.get('errorCode'))
        _, wire, _ = native.CompatContinuation().fixture()
        caption(wire, None)
        scene = dict(envelope=copy.deepcopy(outcome), wire=wire, control=control)
        def server(values):
            if not empty:
                for name in ('metadata', 'playback'):
                    source = values[name]['MediaSources'][0]
                    source['MediaStreams'].append(dict(Index=2,Type='Subtitle',Codec='subrip',Language='en',IsDefault=name=='metadata',IsForced=False,IsExternal=True,IsTextSubtitleStream=True,DeliveryMethod='External'))
                values['metadata']['MediaSources'][0]['DefaultSubtitleStreamIndex'] = 2
            if server_change:
                server_change(values)
        settings = dict(body=SRT, headers={'Content-Type': 'application/x-subrip'})
        settings.update(scenario or {})
        init = 'm.fixtureFiles={}:m.fixtureDownloads=[]:m.fixtureRevision=0:m.fixtureCaptionSamples=[]:m.scenario=ParseJson('+('\"'+json.dumps(settings).replace('\"','\"\"')+'\"')+')\n '
        snapshot = 'm.fixtureGenerationContents.Push(m.video.content)\n m.fixtureCaptionSamples.Push({tracks:m.video.content.SubtitleTracks,config:m.video.content.SubtitleConfig,mode:m.video.globalCaptionMode,notice:m.toast.text,position:m.video.content.playStart,body:FixtureCaptionBody()})'
        overrides = {
            'm.fixtureNativeResults=[]': init+'m.fixtureNativeResults=[]',
            'm.preferences={subtitles:"off",quality:"original"}': 'm.preferences={subtitles:"'+('always' if mode=='on' else 'off')+'",quality:"original"}',
            'subtitleMode:"off",startPositionMs:25000}': 'subtitleMode:"'+mode+'",startPositionMs:25000}',
            'm.fixtureGenerationContents.Push(m.video.content)': snapshot,
            'return {scene:{holderCreated:true': 'return {notice:m.toast.text,samples:m.fixtureCaptionSamples,downloads:m.fixtureDownloads,files:m.fixtureFiles,preference:m.preferences.subtitles,scene:{holderCreated:true',
        }
        return holder.CompatPlaybackTask().transcript(scene=scene,change=server,device_overrides=modern.modern_device(),subtitle_sdk=True,sdk_overrides=overrides)

    def test_always_preference_survives_native_first_compatibility_continuation(self):
        result = modern.ModernCompatFlow().continuation(options={'subtitleMode': 'on'})
        self.assertEqual('compat_prepare_required', result['outcome'].get('errorCode'))
        self.assertEqual('on', result['outcome']['compatContinuation']['subtitleMode'])
        self.assertFalse(any('/playback/start' in q['url'] for q in result['requests']))

    def test_text_subtitle_is_local_before_video_bind_and_removed_after_close(self):
        result = self.scene()
        self.assertTrue(result['scene']['released'])
        sample = result['samples'][0]
        self.assertEqual('On', sample['mode'])
        self.assertEqual('eng', sample['tracks'][0]['Language'])
        uri = sample['tracks'][0]['TrackName']
        self.assertTrue(uri.startswith('tmp:/silo-subtitle-'))
        self.assertEqual(uri, sample['config']['TrackName'])
        self.assertEqual(SRT, sample['body'])
        self.assertEqual({}, result['files'])
        self.assertEqual(1, len(result['downloads']))
        download = result['downloads'][0]
        self.assertEqual('Bearer '+holder.TOKEN, download['headers']['Authorization'])
        self.assertEqual('https://compat.example/media/Videos/'+holder.SOURCE+'/'+holder.SOURCE+'/Subtitles/2/stream.srt?PlaySessionId=play-fixture&CopyTimestamps=true',download['url'])
        self.assertEqual('always',result['preference'])
        posts=[json.loads(q['body']) for q in result['requests'] if '/PlaybackInfo' in q['url']]
        self.assertTrue(all(p['SubtitleStreamIndex']==-1 for p in posts))
        self.assertNotIn(holder.TOKEN,json.dumps(result['results']))

    def test_seek_reuses_whole_title_clock_caption_and_retains_it_until_terminal_drain(self):
        result = self.scene(control='media_roundtrip')
        self.assertEqual(3,len(result['samples']))
        uris = [s['tracks'][0]['TrackName'] for s in result['samples']]
        self.assertEqual(1,len(set(uris)))
        self.assertTrue(all(s['body']==SRT and s['mode']=='On' for s in result['samples']),result['samples'])
        self.assertEqual([25,900,120],[s['position'] for s in result['samples']])
        self.assertEqual(1,len(result['downloads']))
        self.assertEqual({},result['files'])
        self.assertTrue(result['results'][-1]['mediaClosed'])

    def test_empty_verified_inventory_explains_unavailable_and_preserves_always(self):
        result = self.scene(empty=True)
        self.assertTrue(result['scene']['released'])
        self.assertEqual([],result['samples'][0]['tracks'])
        self.assertEqual([],result['downloads'])
        self.assertEqual('always',result['preference'])
        self.assertEqual('No subtitles are available for this file.',result['samples'][0]['notice'])

    def test_off_does_not_fetch_caption(self):
        result = self.scene(mode='off')
        self.assertEqual([],result['downloads'])
        self.assertEqual([],result['samples'][0]['tracks'])
        self.assertEqual('Off',result['samples'][0]['mode'])

    def test_missing_selection_refuses_then_native_recovery_preserves_on(self):
        def missing(values):
            values['metadata']['MediaSources'][0].pop('DefaultSubtitleStreamIndex')
        result = self.scene(server_change=missing)
        self.assertEqual('subtitle_selection_unsupported',result['results'][0]['errorCode'])
        self.assertEqual([],result['downloads'])
        self.assertEqual([],result['samples'])
        self.assertEqual('on',result['scene']['resumeJobs'][0]['params']['subtitleMode'])
        self.assertEqual('Subtitles could not be prepared for this file.',result['notice'])

    def test_invalid_caption_body_and_fetch_cancellation_never_bind_and_remove_partial(self):
        for scenario in ({'body':'<html>not a caption</html>'}, {'size':1048577}, {'cancelOnWait':True}):
            with self.subTest(scenario=scenario):
                result = self.scene(scenario=scenario)
                self.assertEqual([],result['samples'])
                self.assertEqual({},result['files'])
                self.assertTrue(result['privateCleared'])
                self.assertTrue(result['results'][-1]['credentialRevoked'])
