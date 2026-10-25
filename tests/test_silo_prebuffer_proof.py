"""Speculative allocation requires fresh native proof through actual runJob."""
import json
import unittest
from tests import test_silo_compat_continuation as task
from tests.test_silo_single_source_compat_flow import single_source

class PrebufferProof(unittest.TestCase):
    def test_unproven_single_p8_prebuffer_never_allocates_with_either_gate_value(self):
        for enabled in (False,True):
            with self.subTest(enabled=enabled):
                result=task.CompatContinuation().job(enabled=enabled,mutate=single_source,options={'speculativePrebuffer':True,'subtitleMode':None})
                self.assertFalse(result['outcome']['ok'])
                self.assertNotIn('compatContinuation',result['outcome'])
                self.assertNotIn('plan',result['outcome'])
                self.assertFalse(result['outcome'].get('leaseUncertain',False))
                self.assertEqual([],[(q['method'],q['url']) for q in result['requests'] if q['method'] in ('POST','DELETE')])

    def h264(self,options=None,fault=''):
        from unittest.mock import patch
        from tests import test_silo_optional_sdk_resilience as h264
        original=task.CompatContinuation.job
        def job(worker,**kwargs):
            kwargs['options'].update(options or {})
            return original(worker,**kwargs)
        with patch.object(task.CompatContinuation,'job',job):
            return h264.OptionalSDKResilience().start(fault,original=True)

    def test_proven_h264_aac_prebuffer_keeps_exact_foreground_wire_request(self):
        ordinary=self.h264()
        preload=self.h264({'speculativePrebuffer':True,'subtitleMode':None})
        self.assertTrue(ordinary['outcome']['ok'],ordinary['outcome'])
        self.assertTrue(preload['outcome']['ok'],preload['outcome'])
        self.assertEqual(ordinary['requests'],preload['requests'])
        self.assertEqual(1,sum(q['method']=='POST' for q in preload['requests']))
        self.assertFalse(any(q['method']=='DELETE' for q in preload['requests']))

    def test_source_bound_level50_hdr10_prebuffer_keeps_native_route(self):
        from tests import test_silo_level50_hdr10 as level50
        result=level50.Level50HDR10().start(options={'speculativePrebuffer':True,'subtitleMode':None})
        self.assertTrue(result['outcome']['ok'],result['outcome'])
        self.assertEqual('731',result['outcome']['plan']['versionId'])
        start=json.loads(next(q['body'] for q in result['requests'] if q['method']=='POST'))
        self.assertEqual('731',start['file_id'])
        self.assertEqual('2160p',start['client_capabilities']['max_resolution'])
        self.assertEqual({'hdr10':True,'hdr10_plus':False,'hlg':False,'dolby_vision_profiles':[],
                          'hdr10_max_width':3840,'hdr10_max_height':2160,
                          'hdr10_max_frame_rate':30,'hdr10_max_bitrate_kbps':54000},
                         start['client_capabilities']['hdr_details'])
        self.assertEqual(1,sum(q['method']=='POST' for q in result['requests']))
        self.assertFalse(any(q['method']=='DELETE' for q in result['requests']))

    def test_missing_fresh_detail_or_proof_facts_cannot_allocate(self):
        for fault in ('mode_invalid','avc','aac'):
            with self.subTest(fault=fault):
                result=self.h264({'speculativePrebuffer':True,'subtitleMode':None},fault)
                self.assertNotEqual('task_failed',result['outcome'].get('errorCode'))
                self.assertFalse(any(q['method'] in ('POST','DELETE') for q in result['requests']))
        result=task.CompatContinuation().job(options={'speculativePrebuffer':True,'detail':None})
        self.assertNotEqual('task_failed',result['outcome'].get('errorCode'))
        self.assertFalse(any(q['method'] in ('POST','DELETE') for q in result['requests']))

    def test_positive_cap_below_proven_source_bitrate_defers_to_foreground(self):
        result=self.h264({'speculativePrebuffer':True,'bandwidthCapKbps':1000})
        self.assertFalse(result['outcome']['ok'])
        self.assertFalse(any(q['method'] in ('POST','DELETE') for q in result['requests']))

    def test_actual_prebuffer_callback_clears_refused_slot_without_loading_or_failure_ui(self):
        import json
        from tests import test_silo_ui_settings_policy as scene
        refused=task.CompatContinuation().job(enabled=False,mutate=single_source,options={'speculativePrebuffer':True,'subtitleMode':None})['outcome']
        encoded=json.dumps(refused).replace('"','""')
        actual=scene.SiloUISettingsPolicyTests().component('SiloUIPlayer.brs','''
            m.calls=[]:m.provider="silo":m.view="detail":m.playToken=1:m.playLoading=false:m.preferences={quality:"original",subtitles:"off"}
            PlayerPrebuffer({itemId:"fixture-item"},[{versionId:"731"}],[],{})
            token=m.prebuf.token
            PlayerResult("play_prebuf",ParseJson("'''+encoded+'''"),{},token)
            print FormatJson({slotCleared:m.prebuf=invalid,loading:m.playLoading,failureUi:m.playbackFailureDialog<>invalid,calls:m.calls})
        ''',helpers='''
            sub HomeCacheYield()
            end sub
            sub Api(action as String,params as Object,purpose as String,extra=invalid as Dynamic,provider="" as String)
                m.calls.Push(purpose)
            end sub
        ''')
        self.assertEqual({'slotCleared':True,'loading':False,'failureUi':False,'calls':['play_prebuf']},actual)
