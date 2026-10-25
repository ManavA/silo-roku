"""Fractional wire seconds through actual recovery Task and caption binding."""
import json
from pathlib import Path
import unittest
from tests import test_silo_replan_task as replan
from tests import test_silo_selected_subtitle_prepare as prepare
from tests.test_silo_selected_subtitle_worker import decision_with_selected

ROOT=Path(__file__).resolve().parents[1]

class SiloTimelinePrecisionTests(unittest.TestCase):
    def recovery(self, *, offset=306.3064, player=0.694, position=307000, seekable=True, mutate=None):
        params=replan.SiloReplanTaskTests().params()
        params.update(qualityPreference='original',positionMs=position,failureClassification='decoder_failure')
        params['plan']['siloPlayback']['mediaAuthMode']='api_header_v1'
        params['plan']['siloPlayback']['selectedTracks']['subtitle']={'id':'file:f1:subtitle:1','index':1}
        raw=decision_with_selected('session-0001')
        raw['session_id']='session-0001'
        plan=raw['playback_plan']
        plan.update(plan_id='plan-0002',plan_attempt_key='plan-key-0002',delivery='server_transcode_hls',
                    effective_recipe={'video_codec':'h264','audio_codec':'aac','audio_channels':2,'dynamic_range':'sdr','width':1920,'height':1080},
                    transformations=[{'name':'video_to_h264','executor':'server','recipe_version':'2'},
                                     {'name':'audio_to_aac','executor':'server','recipe_version':'4'}])
        plan['stream'].update(url='/api/v2/playback/transcode/session-0001/master.m3u8',protocol='hls',container='hls')
        plan['timeline'].update(timeline_offset_seconds=offset,player_start_seconds=player,can_seek_anywhere=seekable)
        session={'baseUrl':'https://silo.example','sourceId':'silo:synthetic','profileId':'owner',
                 'deviceId':'fixture-device','accessToken':'synthetic-access','profileToken':'synthetic-profile'}
        job={'provider':'silo','action':'playback_replan','sourceId':session['sourceId'],'profileId':session['profileId'],
             'generation':7,'requestId':13,'params':params}
        cap=json.loads((ROOT/'tests/fixtures/silo/playback_capabilities.json').read_text())
        cap.update(installation_id='install-0001',features=['header_authenticated_media_v1'],
                   deliveries=['original_http','server_transcode_hls'])
        if mutate:mutate(job,raw)
        return prepare.SelectedSubtitlePreparationTests().run_job(job_override=job,session_override=session,
            responses_override=[{'statusCode':200,'body':json.dumps(cap)},{'statusCode':200,'body':json.dumps(raw)}])

    def test_fractional_recovery_timeline_keeps_selected_vtt_bound_to_current_owner(self):
        # Real Roku's306.306s JSON Float produced306305.99975586ms in048d.
        # The host interpreter rounds Float to7 significant digits, hiding that
        # noise. This valid float64 source origin retains a fractional ms there
        # and reaches the identical real Task owner/transport refusal.
        result=self.recovery()
        self.assertTrue(result['outcome']['ok'],result)
        plan=result['outcome']['plan']
        self.assertEqual('hls',plan['streamFormat'])
        self.assertIn('subtitleTransport',plan,result)
        self.assertEqual('sidecar_pending',plan['selectedSubtitle']['kind'])
        self.assertEqual(306306,plan['timelineOffsetMs'])
        self.assertAlmostEqual(694,plan['startPositionMs'],delta=0.5)
        self.assertEqual(307000,plan['originalResumeMs'])
        owner=plan['subtitleTransport']['owner']
        self.assertEqual((7,13,'plan-key-0002',306306),tuple(owner[k] for k in
            ('generation','requestId','planAttemptKey','timelineOffsetMs')))
        self.assertEqual(plan['subtitleTransport']['uri'],result['binding']['uri'])
        self.assertEqual([],result['downloads'])
        self.assertNotIn('subtitleArtifact',plan)

    def test_offset_canonicalization_preserves_source_position_and_whole_controls(self):
        cases=[(0,0,0,0,0),(12.5,0.5,13000,12500,500),
               (306.306,0.694,307000,306306,694),
               (306.30599975586,0.694,307000,306306,694),
               (1.0006,0.0002,1000.8,1001,0.2),
               (604799.9,0.1,604800000,604799900,100),
               (604800,0,604800000,604800000,0)]
        for offset,player,position,expected_offset,expected_player in cases:
            with self.subTest(offset=offset,position=position):
                result=self.recovery(offset=offset,player=player,position=position)
                self.assertTrue(result['outcome']['ok'],result)
                plan=result['outcome']['plan']
                self.assertEqual(expected_offset,plan['timelineOffsetMs'])
                self.assertAlmostEqual(expected_player,plan['startPositionMs'],delta=0.01)
                self.assertEqual(position,plan['originalResumeMs'])
                self.assertIsNotNone(result['binding'],result)
                self.assertEqual(expected_offset,plan['subtitleTransport']['owner']['timelineOffsetMs'])
                # Source reporting may differ by at most half a millisecond;
                # the raw requested/restored player position remains intact.
                self.assertAlmostEqual(position,plan['startPositionMs']+plan['timelineOffsetMs'],delta=0.5)

    def test_nonseekable_checks_raw_restoration_tolerance_before_offset_rounding(self):
        for target,accepted in [(1001,True),(1002,True),(1002.1,False)]:
            with self.subTest(target=target):
                result=self.recovery(offset=1.0004,player=0.0006,position=target,seekable=False)
                self.assertEqual(accepted,result['outcome']['ok'],result)
                if accepted:
                    plan=result['outcome']['plan']
                    self.assertEqual(1000,plan['timelineOffsetMs'])
                    self.assertAlmostEqual(0.6,plan['startPositionMs'],delta=0.00001)
                    self.assertEqual(target,plan['originalResumeMs'])
                    self.assertIsNotNone(result['binding'],result)
                else:
                    self.assertEqual('invalid_response',result['outcome']['errorCode'])
                    self.assertNotIn('plan',result['outcome'])

    def test_invalid_raw_timing_never_becomes_valid_by_rounding(self):
        cases=[dict(offset=-0.0001),dict(offset=604801),dict(player=-0.0001),dict(player=604801),
               dict(offset=True),dict(player=False),dict(seekable=1),
               dict(offset=1.0006,position=1000.4),dict(position=-0.1),dict(position=604800001)]
        for changes in cases:
            with self.subTest(changes=changes):
                result=self.recovery(**changes)
                self.assertFalse(result['outcome']['ok'],result)
                self.assertNotIn('plan',result['outcome'])
                self.assertIsNone(result['binding'])
                self.assertEqual([],result['downloads'])

    def test_fractional_timing_does_not_authorize_foreign_routes_receipts_or_owner(self):
        def foreign_media(job,raw):
            raw['playback_plan']['stream']['url']='https://foreign.example/api/v2/playback/transcode/session-0001/master.m3u8'
        def foreign_tracks(job,raw):
            raw['playback_plan']['selected_tracks']['subtitle']={'id':'file:f1:subtitle:0','index':0}
        def foreign_profile(job,raw):
            job['profileId']='foreign'
        for mutate in [foreign_media,foreign_tracks,foreign_profile]:
            with self.subTest(mutate=mutate.__name__):
                result=self.recovery(mutate=mutate)
                self.assertFalse(result['outcome']['ok'],result)
                self.assertIsNone(result['binding'])
                self.assertEqual([],result['downloads'])
        def caption_secret(job,raw):
            subtitle=raw['playback_plan']['subtitle']
            subtitle['artifact']['url']+='&token=must-not-publish'
            subtitle['inventory'][1]['url']=subtitle['artifact']['url']
        result=self.recovery(mutate=caption_secret)
        self.assertTrue(result['outcome']['ok'],result)
        plan=result['outcome']['plan']
        self.assertEqual({'Authorization':'Bearer synthetic-access'},plan['headers'])
        self.assertIsNone(result['binding'])
        self.assertNotIn('subtitleTransport',plan)
        self.assertNotIn('must-not-publish',json.dumps(plan))
        self.assertEqual([],result['downloads'])

if __name__=='__main__':unittest.main()
