"""Subtitle receipts retain only enums; explicit Off proof rejects selected work.

Official server 55d0578 protocol_v3.go uses subtitle.mode/track_id/artifact,
selected_tracks.subtitle and TransformationV3.name. QA cce24de additionally
publishes subtitle.embedded; inventory URLs are independent of selection.
Neither source has a subtitle-specific transformation name: unknown transforms
cannot prove Off; video/audio/package transforms alone do not imply burn-in.
"""
import json
from pathlib import Path
import unittest
from tools.brightscript import run_function

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT/'source/adapters/SiloAdapter.brs'

class SiloSubtitleReceiptTests(unittest.TestCase):
    def call(self, name, *args):
        return run_function(ADAPTER, name, list(args))

    def receipt(self):
        return {'subtitle':{'mode':'off'},'selected_tracks':{'audio':{'id':'synthetic'}},'transformations':[]}

    def test_alternate_start_requires_off_receipt_and_retains_intent(self):
        from tests import test_silo_playback_task as worker
        params={'itemId':'fixture-item','fileId':'f1','startPositionMs':12500,
                'subtitleMode':'off','subtitleOffRequired':True}
        for mode in ('off','burn_in'):
            with self.subTest(mode=mode):
                raw=json.loads((ROOT/'tests/fixtures/silo/playback_decision_plan.json').read_text())
                raw['playback_plan']['subtitle']={'mode':mode}
                result=worker.SiloPlaybackTaskTests().run_start(params=params,decision=raw)
                if mode=='off':
                    self.assertTrue(result['outcome']['ok'],result)
                    self.assertTrue(result['outcome']['plan']['siloPlayback']['subtitleOffRequired'])
                else:
                    self.assertFalse(result['outcome']['ok'],result)
                    self.assertEqual('invalid_response',result['outcome']['errorCode'])
                    self.assertEqual(['GET','POST','DELETE'],[r['method'] for r in result['requests']])

    def test_internal_track_change_wire_keeps_failure_and_selection_validation(self):
        fixture=json.loads((ROOT/'tests/fixtures/silo/roku_start_input.json').read_text())
        body={'installation_id':'server-install','protocol_version':3,
              'attempted_plan_keys':[],'attempt_count':1,'quality_preference':'original',
              'position_seconds':12.5,'metered':False,'operation':'track_change',
              'selected_tracks':{'audio':{'id':'file:f1:audio:1','index':1}},
              'client_capabilities':fixture['clientCapabilities'],
              'client_playback_context':fixture['clientPlaybackContext']}
        for key in ['playback_attempt_id','replan_request_id','failed_plan_id','plan_attempt_id','plan_attempt_key']:
            body[key]='synthetic-value-0001'
        self.assertTrue(self.call('SiloReplanBodyValid',body))
        for key,value in [('failure',{'classification':'decoder_failure'}),('operation','invented'),('selected_tracks',{'audio':{'id':'a','index':-1}})]:
            invalid=dict(body);invalid[key]=value
            self.assertFalse(self.call('SiloReplanBodyValid',invalid))

    def test_plan_retains_only_actual_sanitized_subtitle_mode(self):
        decision=json.loads((ROOT/'tests/fixtures/silo/playback_decision_plan.json').read_text())
        session={'baseUrl':'https://silo.example'}
        for mode in ['off','render','convert','burn_in','private-mode',' off ',None,5]:
            decision['playback_plan']['subtitle']={'mode':mode,'track_id':'private-id','artifact':{'url':'https://private.invalid/sub'}}
            plan=self.call('SiloPlaybackPlan',decision,session)
            self.assertTrue(plan['ok'])
            self.assertEqual(mode if mode in ['off','render','convert','burn_in'] else 'unknown',plan['subtitleMode'])
            self.assertNotIn('private',json.dumps(plan))
        decision['playback_plan'].pop('subtitle')
        self.assertEqual('unknown',self.call('SiloPlaybackPlan',decision,session)['subtitleMode'])

    def test_off_allows_inventory_but_no_selection(self):
        raw=self.receipt()
        raw['subtitle'].update(track_id='',artifact=None,embedded=None,inventory=[{'track_id':'inventory-only','url':'https://private.invalid/sub'}])
        self.assertTrue(self.call('SiloSubtitleOffReceipt',raw))

    def test_off_refuses_missing_unknown_or_contradictory_selection(self):
        cases=[{}, {'subtitle':{'mode':'off'}}, {'subtitle':{'mode':'off'},'selected_tracks':[] }]
        for key,value in [('mode','render'),('mode',' off '),('mode',None),('track_id','picked'),('track_id',3),('artifact',{}),('embedded',{})]:
            raw=self.receipt();raw['subtitle'][key]=value;cases.append(raw)
        raw=self.receipt();raw['selected_tracks']['subtitle']={};cases.append(raw)
        raw=self.receipt();raw['selected_tracks']['subtitle']=False;cases.append(raw)
        raw=self.receipt();raw['selected_tracks']['subtitle']=None;cases.append(raw)
        for raw in cases:self.assertFalse(self.call('SiloSubtitleOffReceipt',raw),raw)

    def test_off_refuses_contradictory_subtitle_claims(self):
        for claims in [{'bitmap_overlay':True},{'bitmap_sidecar':True},
                       {'ass_styling_preserved':True},{'reason':'server_burn_in_required'},
                       {'bitmap_overlay':'false'},'invalid']:
            raw=self.receipt();raw['claims']={'subtitles':claims}
            self.assertFalse(self.call('SiloSubtitleOffReceipt',raw),claims)
        raw=self.receipt()
        raw['claims']={'subtitles':{'bitmap_overlay':False,'bitmap_sidecar':False,
                                  'ass_styling_preserved':False,'reason':'subtitles_off'}}
        self.assertTrue(self.call('SiloSubtitleOffReceipt',raw))

    def test_off_refuses_burn_receipt_and_unknown_or_malformed_transform(self):
        for change in [{'decision_reason':'subtitle_burn_in_required'}, {'degradation_warnings':[{'code':'subtitle_burn_in'}]}, {'transformations':[{'name':'unknown_subtitle_work'}]}, {'transformations':[None]}, {'transformations':'bad'}]:
            raw=self.receipt();raw.update(change)
            self.assertFalse(self.call('SiloSubtitleOffReceipt',raw),change)

    def test_off_allows_known_audio_video_packaging_transforms(self):
        raw=self.receipt()
        raw['transformations']=[{'name':name} for name in ['audio_to_aac','video_to_h264','video_to_hevc','server_dv7_to_hdr10','server_dv7_to_dv81','hls_mpegts','hls_separate_audio','hdr_to_sdr_tonemap']]
        self.assertTrue(self.call('SiloSubtitleOffReceipt',raw))

if __name__=='__main__':unittest.main()
