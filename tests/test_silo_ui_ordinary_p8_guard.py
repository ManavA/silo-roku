"""Ordinary native guard authority originates in the actual Task receipt."""
import copy,unittest
from pathlib import Path
from tools.brightscript import run_function
from tests import test_silo_ordinary_p8_original as transport
ROOT=Path(__file__).resolve().parents[1]
POLICY=ROOT/'source/core/SiloUIOriginalPlaybackPolicy.brs'

class OrdinaryP8Guard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result=transport.OrdinaryP8Original().start()
        if not result['outcome']['ok']:raise AssertionError('actual Task receipt unavailable')
        cls.proof=result['outcome']['plan']['originalPlayback']

    def create(self,proof=None):
        return run_function([POLICY],'SiloUIOriginalCreate',[self.proof if proof is None else proof,7,3,0,False])

    def event(self,state,kind,now=1000,**values):
        return run_function([POLICY],'SiloUIOriginalReduce',[state,dict(kind=kind,token=7,generation=state['generation'],nowMs=now,**values)])

    def tracks(self):
        return [dict(Track='native-dts',Format='DTS Coherent Acoustics',Language='eng',Channels=6),
                dict(Track='native-ac3',Format='Dolby Digital',Language='eng',Channels=2)]

    def test_qualified_ordinary_retry_reselects_only_current_ac3_after_buffering(self):
        state=self.event(self.create(),'observation',nativeState='buffering')['state']
        state=self.event(state,'inventory',now=2000,inventory=self.tracks())['state']
        self.assertFalse(state['experimental'])
        self.assertTrue(state.get('initialRestartMapping',state.get('initialrestartmapping')))
        state=self.event(state,'observation',now=5000,nativeState='finished')['state']
        state=self.event(state,'observation',now=6000,nativeState='buffering')['state']
        selected=self.event(state,'inventory',now=6100,inventory=self.tracks(),provenance='same_content_restart',bindingValidated=True)
        self.assertEqual(dict(kind='select',trackId='native-ac3'),selected['command'])
        state=selected['state']
        wrong=self.event(state,'observation',now=7000,nativeState='playing',audioTrack='native-dts',audioFormat='dts',positionMs=100)
        self.assertEqual('selected',wrong['state']['phase'])
        state=self.event(state,'observation',now=8000,nativeState='playing',audioTrack='native-ac3',audioFormat='ac3',positionMs=100)['state']
        self.assertEqual('selected',state['phase'])
        state=self.event(state,'observation',now=9000,nativeState='playing',audioTrack='native-ac3',audioFormat='ac3',positionMs=1100)['state']
        self.assertEqual('verified_playing',state['phase'])

    def test_exact_qualified_startup_budget_is_not_experimental_or_unbounded(self):
        state=self.create()
        self.assertIsNone(self.event(state,'tick',now=59999)['command'])
        self.assertEqual('startup_timeout',self.event(state,'tick',now=60000)['command']['reason'])
        for change in ('missing','wrong_profile','wrong_audio'):
            proof=copy.deepcopy(self.proof)
            if change=='missing':proof.pop('qualifiedRoute')
            if change=='wrong_profile':proof['dolbyVisionProfile']=7
            if change=='wrong_audio':proof['audioIdentity'].update(channels=6,layout='5.1');proof['sourceAudio'][1].update(channels=6,layout='5.1')
            normal=self.create(proof)
            self.assertEqual('startup_timeout',self.event(normal,'tick',now=30000)['command']['reason'])
