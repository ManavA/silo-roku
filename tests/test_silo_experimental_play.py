"""Request-scoped private Original experiment; shipping gates remain disabled."""
import copy
import json
import unittest
from tests import test_silo_p8_original_transport as transport
from tests import test_silo_original_p8_policy as pure

class ExperimentalPlayTests(unittest.TestCase):
    def setUp(self):
        self.worker=transport.SiloP8OriginalTransportTests()
        self.policy=pure.SiloOriginalP8PolicyTests()
        self.options=dict(experimentalOriginal=True,autoVersion=False,subtitleMode='off',qualityPreference='original')
    def start(self,options=None,config=None,args=None):
        opts=dict(self.options);opts.update(options or {})
        return self.worker.worker(*(args or self.worker.inputs()),active=False,options=opts,config=config)
    def test_scoped_optin_accepts_exact_guarded_receipt_and_global_flags_stay_false(self):
        result=self.start()
        self.assertTrue(result['outcome']['ok'],result)
        self.assertTrue(result['outcome']['plan']['experimentalOriginal'])
        self.assertIn('originalPlayback',result['outcome']['plan'])
        self.assertEqual(['client_managed_dynamic_range_v1'],self.worker.claims(result))
        for name in ('SiloOriginalActivationEnabled','SiloP8OriginalActivationEnabled'):
            self.assertFalse(self.policy.call(name))
    def test_patched_without_eligible_copy_keeps_explicit_original_scoped(self):
        result=self.start(config={'features':['native_hls_mpegts_v1'],'runtimeDevice':True})
        self.assertTrue(result['outcome']['ok'],result)
        plan=result['outcome']['plan']
        self.assertTrue(plan['experimentalOriginal'])
        self.assertNotIn('qualifiedRoute',plan['originalPlayback'])
        self.assertEqual(['GET','GET','POST'],[r['method'] for r in result['requests']])

    def test_os16_p7_start_guarded_and_experimental_audio_replan_refused(self):
        from tests.test_silo_original_transport import SiloOriginalTransportTests
        args=SiloOriginalTransportTests().inputs()
        result=self.start(args=args,options={"audioTrackIndex":1,"audioTrackId":"file:731:audio:1"})
        self.assertTrue(result['outcome']['ok'],result)
        self.assertTrue(result['outcome']['plan']['experimentalOriginal'])
        result=self.start(config={'replan':copy.deepcopy(self.worker.inputs()[2]),'audioChange':0})
        self.assertFalse(result['outcome']['ok'],result)
        self.assertEqual(['GET','GET','POST'],[r['method'] for r in result['requests']])

    def test_default_truehd_requires_explicit_compatible_choice(self):
        from tests.test_silo_original_transport import SiloOriginalTransportTests
        args=SiloOriginalTransportTests().inputs()
        for probe in (False,True):
            result=self.start(args=args,config={'probe':probe})
            if probe:
                self.assertFalse(result['outcome']['data']['available'],result)
            else:
                self.assertFalse(result['outcome']['ok'],result)
            self.assertEqual(['GET','GET'],[r['method'] for r in result['requests']])

    def test_invalid_intent_never_allocates(self):
        cases=[({'autoVersion':True},{}),({'autoVersion':None},{}),({'speculativePrebuffer':True},{}),({'qualityPreference':'1080p'},{}),({'subtitleMode':'unknown'},{}),({'experimentalOriginal':'true'},{}),({}, {'noDetail':True}),({'fileId':'732'},{}),({'subtitleTrackIndex':0},{})]
        for options,config in cases:
            with self.subTest(options=options,config=config):
                result=self.start(options,config)
                self.assertFalse(result['outcome']['ok'],result)
                self.assertNotIn('POST',[r['method'] for r in result['requests']])
    def test_fresh_unproven_source_never_allocates(self):
        cases=[(None,{'capability':{'allowed':False}}),(None,{'rejectOutput':True}),(None,{'rejectVideo':True}),(None,{'capability':{'features':None}})]
        args=self.worker.inputs();args[1]['versions'][0]['video_tracks'][0]['dv_profile']=5;cases.append((args,{}))
        for args,config in cases:
            with self.subTest(config=config,args=args is not None):
                result=self.start(config=config,args=args)
                self.assertFalse(result['outcome']['ok'],result)
                self.assertNotIn('POST',[r['method'] for r in result['requests']])
    def test_nonoriginal_receipt_refuses_and_deletes_once_without_fallback(self):
        args=self.worker.inputs()
        from tests.test_silo_original_transport import SiloOriginalTransportTests
        args=(args[0],args[1],SiloOriginalTransportTests().ordinary_hls(args[2]))
        result=self.start(args=args)
        self.assertFalse(result['outcome']['ok'],result)
        self.assertEqual(['GET','GET','POST','DELETE'],[r['method'] for r in result['requests']])
    def test_experimental_replan_requires_new_consent_without_http(self):
        args=self.worker.inputs()
        result=self.start(config={'replan':copy.deepcopy(args[2])})
        self.assertFalse(result['outcome']['ok'],result)
        self.assertEqual(['GET','GET','POST'],[r['method'] for r in result['requests']])
    def test_probe_fresh_gets_only_and_returns_no_claims_or_plan(self):
        for config,available in [({},True),({'features':['native_hls_mpegts_v1']},True),({'rejectOutput':True},False)]:
            with self.subTest(config=config):
                result=self.start(config=dict(config,probe=True))
                self.assertTrue(result['outcome']['ok'],result)
                self.assertEqual(available,result['outcome']['data']['available'])
                self.assertEqual(['GET','GET'],[r['method'] for r in result['requests']])
                self.assertEqual({'available','reason'},set(result['outcome']['data']))
    def test_os16_p7_optin_accepts_fresh_firmware_and_normal_policy_unchanged(self):
        f=json.loads((pure.ROOT/'tests/fixtures/silo/original_p7_candidate.json').read_text())
        f['deviceSnapshot']['os']=self.policy.fixture()['deviceSnapshot']['os']
        self.assertFalse(self.policy.eligible(f)['ok'])
        f['requestIntent']['experimentalOriginal']=True
        self.assertTrue(self.policy.eligible(f,{'index':1,'explicit':True})['ok'])
        f['deviceSnapshot']['os']['build']='835'
        self.assertTrue(self.policy.eligible(f,{'index':1,'explicit':True})['ok'])
    def test_server_helper_requires_known_success_and_exact_advertised_recipe(self):
        cap=dict(allowed=True,state='available',installationId='server-install',protocolVersions=[3],deliveries=['original_http','server_remux_hls'],features=[])
        self.assertTrue(self.policy.call('SiloExperimentalServer',cap))
        for feature in ('native_hls_mpegts_v1','native_hls_separate_audio_v1'):
            self.assertTrue(self.policy.call('SiloExperimentalServer',dict(cap,features=[feature])))
        for change in [dict(allowed=False),dict(state='unknown'),dict(protocolVersions=['3']),dict(installationId='https://bad'),dict(deliveries=[]),dict(features=None)]:
            changed=dict(cap,**change)
            self.assertFalse(self.policy.call('SiloExperimentalServer',changed),change)

    def test_runtime_qualified_devices_get_optin_without_ordinary_authority(self):
        for profile in (7,8):
            for model_type in ('STB','TV'):
                f=self.policy.fixture()
                if profile == 7:
                    f=json.loads((pure.ROOT/'tests/fixtures/silo/original_p7_candidate.json').read_text())
                f['deviceSnapshot'].update(model='runtime-device',modelNumber='runtime-number',modelType=model_type,videoMode='2160p30')
                f['deviceSnapshot']['os']=dict(major='17',minor='0',revision='1',build='100')
                self.assertFalse(self.policy.eligible(f,{'index':0,'explicit':True})['ok'])
                f['requestIntent']['experimentalOriginal']=True
                selected={'index':1 if profile == 7 else 0,'explicit':True}
                result=self.policy.eligible(f,selected)
                self.assertTrue(result['ok'],result)
                self.assertNotIn('qualifiedRoute',result['proof'])
                self.assertEqual([],self.policy.call('SiloOriginalClaims',result['proof']))

    def test_optin_requires_fresh_complete_identity_and_positive_output_queries(self):
        changes=[('fresh',False),('model',''),('modelType',None),('modelNumber',{}),('os',dict(major='17',minor='0',revision='1',build='unknown')),('videoMode','1080p60'),('videoMode','2160punknown'),('hdr10',False),('outputFingerprint','')]
        for key,value in changes:
            f=self.policy.fixture();f['requestIntent']['experimentalOriginal']=True
            f['deviceSnapshot'][key]=value
            self.assertFalse(self.policy.eligible(f)['ok'],key)
        for field in ('videoQuery','audioQueries'):
            for result in (False,None,'true'):
                f=self.policy.fixture();f['requestIntent']['experimentalOriginal']=True
                target=f['deviceSnapshot'][field]
                if isinstance(target,list):target=target[0]
                target['result']=result
                self.assertFalse(self.policy.eligible(f)['ok'],(field,result))

    def test_runtime_device_start_uses_exact_guarded_receipt_without_ordinary_promotion(self):
        result=self.start(config={'runtimeDevice':True})
        self.assertTrue(result['outcome']['ok'],result)
        plan=result['outcome']['plan']
        self.assertTrue(plan['experimentalOriginal'])
        self.assertNotIn('qualifiedRoute',plan['originalPlayback'])
        self.assertIn('runtime-device/runtime-number/17.0.1.100',plan['originalPlayback']['outputFingerprint'])
        args=self.worker.inputs();args[2]['playback_plan']['selected_tracks']['audio']['index']=1
        result=self.start(args=args,config={'runtimeDevice':True})
        self.assertFalse(result['outcome']['ok'],result)
        self.assertEqual(['GET','GET','POST','DELETE'],[r['method'] for r in result['requests']])

    def test_optin_accepts_documented_2160p_modes_only(self):
        modes=['2160p'+rate+suffix for suffix in ('','b10') for rate in ('24','25','30','50','60')]
        modes+=['2160p30Dv','2160p60Dv']
        for mode in modes+['1080p60Dv','4320p60','bad2160p60','2160p60Hdr']:
            f=self.policy.fixture();f['requestIntent']['experimentalOriginal']=True
            f['deviceSnapshot']['videoMode']=mode
            result=self.policy.eligible(f)
            self.assertEqual(mode in modes,result['ok'],(mode,result))
