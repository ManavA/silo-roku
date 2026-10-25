"""Actual Start→Replan/seek HTTP seams; receiver query drift is SDK-only.

Retained source/recipe identities stay unchanged. No media or device operations.
"""
import unittest
from unittest.mock import patch
from tests import test_silo_seek_reanchor_task as seek


class NativeAudioChannelRecovery(unittest.TestCase):
    def recovery(self, action, *, change=True, converted=False):
        helper=seek.SiloSeekReanchorTaskTests()
        initial=helper.decision()
        returned=helper.decision(125.375,124,plan_id='plan-0002' if action=='playback_replan' else 'plan-0001',
                                 key='plan-key-0002' if action=='playback_replan' else 'plan-key-0001')
        for decision in (initial,returned):
            plan=decision['playback_plan']
            plan['source'].update(audio_codec='truehd' if converted else 'ac3',audio_channels=8 if converted else 6,audio_layout='7.1' if converted else '5.1(side)')
            plan['effective_recipe'].update(audio_codec='aac' if converted else 'ac3',audio_channels=2 if converted else 6,audio_layout='stereo' if converted else '5.1(side)')
            plan['claims']['audio'].update(codec='aac' if converted else 'ac3',passthrough=False)
            if converted:
                plan['transformations'].append(dict(name='audio_to_aac',executor='server',recipe_version='4',validated_claims=['audio_decode']))
        sdk=seek.playback.BOUNDARIES
        generic='if format.chcnt = invalid then return {result:(format.codec="aac" and format.passthru=0) or (format.codec="eac3" and format.passthru=1)}'
        replacement='''if format.codec="ac3" and format.chcnt=6
            if m.fixtureAudioChanged=true
                if m.changedAudioQueries=invalid then m.changedAudioQueries=0
                m.changedAudioQueries++
                return {result:false}
            end if
            return {result:format.passthru=0}
        end if
        if format.chcnt=invalid then return {result:(format.codec="aac" and format.passthru=0) or (format.codec="eac3" and format.passthru=1) or (format.codec="ac3" and format.passthru=0)}'''
        self.assertIn(generic,sdk)
        sdk=sdk.replace(generic,replacement,1)
        if change:
            sdk=sdk.replace('response = m.responses.Shift()',
                'if request.method="POST" and Instr(1,request.url,"/replan")>0 then FixtureSiloDevice().fixtureAudioChanged=true\n    response = m.responses.Shift()',1)
        wrapper=seek.WRAPPER
        old='return {start:captured,outcome:outcome,requests:m.requests,timeouts:m.timeouts}'
        self.assertIn(old,wrapper)
        wrapper=wrapper.replace(old,'return {start:captured,outcome:outcome,requests:m.requests,timeouts:m.timeouts,changedAudioQueries:FixtureSiloDevice().changedAudioQueries}',1)
        config={} if action=='playback_seek_reanchor' else {'action':action}
        with patch.object(seek.playback,'BOUNDARIES',sdk),patch.object(seek,'WRAPPER',wrapper):
            return helper.run_seek(initial=initial,returned=returned,config=config)

    def test_newly_unsupported_returned_audio_never_adopts_replan_or_seek(self):
        for action in ('playback_replan','playback_seek_reanchor'):
            with self.subTest(action=action):
                result=self.recovery(action)
                self.assertFalse(result['outcome']['ok'],result['outcome'])
                self.assertNotIn('plan',result['outcome'])
                self.assertEqual('unsupported_stream',result['outcome']['errorCode'])
                self.assertTrue(result['outcome']['leaseUncertain'])
                expected='plan-0002' if action=='playback_replan' else 'plan-0001'
                self.assertEqual(expected,result['outcome']['controlReceipt']['planId'])
                self.assertGreaterEqual(result['changedAudioQueries'],2)
                self.assertFalse(any(r['method']=='DELETE' for r in result['requests']))
                self.assertEqual(2,sum(r['method']=='POST' for r in result['requests']))

    def test_supported_returned_audio_and_source_truehd_to_aac_conversion_stay_playable(self):
        for action in ('playback_replan','playback_seek_reanchor'):
            for converted in (False,True):
                with self.subTest(action=action,converted=converted):
                    result=self.recovery(action,change=False,converted=converted)
                    self.assertTrue(result['outcome']['ok'],result['outcome'])
                    self.assertEqual('session-0001',result['outcome']['plan']['sessionId'])
                    self.assertEqual(2,sum(r['method']=='POST' for r in result['requests']))
                    self.assertFalse(any(r['method']=='DELETE' for r in result['requests']))
