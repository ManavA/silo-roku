"""Real audio PlayItem → Task continuation → Scene admission, SDK leaves only.

The holder node is an SDK command sink in this slice: these tests prove admission
and retained intent, not compatibility HTTP allocation or native decoding.
"""
import copy
import json
import unittest
from unittest.mock import patch

from tests import test_silo_ui_native_hdr10_scene as scene
from tests import test_silo_p7_producer_flow as producer
from tests.test_silo_ui_compat_continuation import SCENE_SDK


class P7SceneFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        producer.P7ProducerFlow.setUpClass()
        cls.job = copy.deepcopy(producer.P7ProducerFlow.scene_job)
        cls.started = producer.P7ProducerFlow().run_task()['outcome']
        assert cls.started['errorCode'] == 'compat_prepare_required'
        bridge = scene.OrdinaryNativeHdr10Scene()
        detail_job = bridge.scene()['tasks'][0]['job']
        cls.detail = producer.task.CompatContinuation().job(enabled=False, scope=detail_job,
            mutate=producer.fixture, device=producer.DEVICE)['outcome']

    def scene(self, *, change='', mutate=None, explicit=False, duplicate=False):
        started = copy.deepcopy(self.started)
        if mutate:
            mutate(started)
        execute = scene.run_brightscript
        encoded = json.dumps(self.detail['data']['versions']).replace('"', '""')
        def launch(files, body, *, root):
            for path in files:
                text = path.read_text()
                text = text.replace('CreateObject("roSGNode","Timer")','FixtureCompatTimer()')
                text = text.replace('AppRegistrySection("silo")','FixtureSceneRevisionSection()')
                if path.name == 'SiloUICompatPlayback.brs':
                    text = text.replace('CreateObject("roSGNode", "SiloCompatTask")', 'FixtureP7Holder()')
                if path.name == 'SDK.brs':
                    for old,new in producer.DEVICE.items():
                        text = text.replace(old,new)
                    text += SCENE_SDK.split('function FixtureSceneAgent()',1)[0]
                    text += '''
function FixtureP7Holder() as Object
 GetGlobalAA().holderCount++
 return {observeField:sub(field as String,callback as String)
 end sub}
end function
'''
                path.write_text(text)
            body = body.replace(' GetGlobalAA().tasks=[]', ' GetGlobalAA().tasks=[]:GetGlobalAA().holderCount=0',1)
            entry = '''m.view="detail":m.detailToken=4
 m.detailVersions=ParseJson("''' + encoded + '''")
 choices=SiloUIDetailAudioChoices("silo",item,m.detailVersions,"")
 choice=choices[1]:choice.visit=m.detailToken:choice.sourceId=m.sourceId:choice.profileId=m.profileId:choice.generation=m.generation
 PlayItem(item,0,"''' + ('731' if explicit else '') + '''",choice)'''
            assert body.count('  PlayItem(item,0)') == 1
            body = body.replace('  PlayItem(item,0)',entry,1)
            body = body.replace('  onApiResult(FixtureEvent(outcome))',
                '  if outcome.errorCode="compat_prepare_required"\n'+change+'\n  end if\n  onApiResult(FixtureEvent(outcome))',1)
            if duplicate:
                body = body.replace('  onApiResult(FixtureEvent(outcome))', '  onApiResult(FixtureEvent(outcome))\n  if outcome.errorCode="compat_prepare_required" then onApiResult(FixtureEvent(outcome))',1)
            body = body.replace('print FormatJson({heroCandidateEligible:', '''command=invalid:current=false
 if m.compatPreparation<>invalid
  command=m.compatPreparation.task.command
  current=SiloUICompatCurrent(m.compatPreparation)
 end if
 print FormatJson({holderCreated:m.compatPreparation<>invalid,holderCount:GetGlobalAA().holderCount,command:command,current:current,loading:m.playLoading,versionExplicit:m.playVersionExplicit,normalizedFile:m.playSelectedVersion,heroCandidateEligible:''',1)
            return execute(files,body,root=root)
        with patch.object(scene,'run_brightscript',side_effect=launch):
            return scene.OrdinaryNativeHdr10Scene().scene([self.detail,started])

    def test_real_audio_only_continuation_admits_exact_p7_prepare(self):
        result = self.scene()
        self.assertTrue(result['holderCreated'],result)
        self.assertFalse(result['versionExplicit'])
        self.assertEqual('731',result['normalizedFile'])
        self.assertTrue(result['current'])
        command = result['command']
        self.assertEqual('prepare',command['action'])
        self.assertEqual(producer.KIND,command['params']['eligibilityKind'])
        self.assertEqual(('731','file:731:audio:1',1),tuple(command['params'][key] for key in ('fileId','audioTrackId','audioTrackIndex')))
        self.assertEqual(['detail','playback_start'],[entry['job']['action'] for entry in result['tasks']])

    def test_malformed_public_task_detail_refuses_without_holder(self):
        result = self.scene(change='''for each key in m.pending
 m.pending[key].task.job.params.detail = false
end for''')
        self.assertFalse(result['holderCreated'])
        self.assertFalse(result['loading'])
        self.assertFalse(result['bound'])

    def test_explicit_version_choice_cannot_admit_audio_only_p7_handoff(self):
        result = self.scene(explicit=True)
        self.assertTrue(result['versionExplicit'])
        self.assertEqual('731',result['normalizedFile'])
        self.assertFalse(result['holderCreated'])
        self.assertFalse(result['loading'])
        self.assertEqual(0,result['holderCount'])

    def test_stale_detail_choice_and_owner_cannot_create_a_holder(self):
        for change in ('m.detailToken++',
                       'm.detailVersions[0].audioTracks[1].codec="eac3"',
                       'm.profileId="other-profile"', 'm.generation++'):
            with self.subTest(change=change):
                result = self.scene(change=change)
                self.assertFalse(result['holderCreated'])
                self.assertFalse(result['bound'])
                self.assertEqual(0,result['holderCount'])
                self.assertEqual(['detail','playback_start'],[e['job']['action'] for e in result['tasks']])

    def test_missing_wrong_or_malformed_kind_and_selector_cannot_admit(self):
        def missing(outcome):
            del outcome['compatContinuation']['eligibilityKind']
        def wrong(outcome):
            outcome['compatContinuation']['eligibilityKind']='experimental_query_p8_ts_v1'
        def malformed(outcome):
            outcome['compatContinuation']['eligibilityKind']=True
        def selector(outcome):
            outcome['compatContinuation']['audioTrackIndex']='1'
        for mutate in (missing,wrong,malformed,selector):
            with self.subTest(mutate=mutate.__name__):
                result = self.scene(mutate=mutate)
                self.assertFalse(result['holderCreated'])
                self.assertFalse(result['loading'])
                self.assertEqual(0,result['holderCount'])
                self.assertFalse(result['bound'])

    def test_duplicate_callback_cannot_allocate_a_second_holder(self):
        result = self.scene(duplicate=True)
        self.assertTrue(result['holderCreated'])
        self.assertEqual(1,result['holderCount'])
        self.assertTrue(result['current'])
