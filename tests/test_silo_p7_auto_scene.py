"""Real no-choice PlayItem → actual Task Auto result → Scene admission.

The holder is an SDK command sink here. These tests establish intent and source
correlation, not compatibility allocation, native decoding or hardware support.
"""
import copy
import json
import unittest
from unittest.mock import patch

from tests import test_silo_ui_native_hdr10_scene as scene
from tests import test_silo_p7_auto_producer as auto
from tests import test_silo_p7_auto_holder as auto_holder
from tests import test_silo_p7_producer_flow as explicit
from tests.test_silo_ui_compat_continuation import SCENE_SDK


class P7AutoScene(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        auto.P7AutoProducer.setUpClass()
        cls.detail=copy.deepcopy(auto.P7AutoProducer.detail)
        cls.started=auto.P7AutoProducer().run_auto()['outcome']
        assert cls.started['errorCode']=='compat_prepare_required',cls.started

    def scene(self, *, mutate=None, change='', duplicate=False, device=None, detail=None, started=None, prepared=None):
        detail=copy.deepcopy(self.detail if detail is None else detail)
        started=copy.deepcopy(self.started if started is None else started)
        if mutate:
            mutate(started)
        execute=scene.run_brightscript
        def launch(files,body,*,root):
            for path in files:
                text=path.read_text()
                text=text.replace('CreateObject("roSGNode","Timer")','FixtureCompatTimer()')
                text=text.replace('AppRegistrySection("silo")','FixtureSceneRevisionSection()')
                if path.name=='SiloUICompatPlayback.brs':
                    text=text.replace('CreateObject("roSGNode", "SiloCompatTask")','FixtureAutoHolder()')
                if path.name=='SDK.brs':
                    for old,new in (device or explicit.DEVICE).items():
                        text=text.replace(old,new)
                    text+=SCENE_SDK.split('function FixtureSceneAgent()',1)[0]
                    text+='''
function FixtureAutoHolder() as Object
 GetGlobalAA().holderCount++
 return {observeField:sub(field as String,callback as String)
 end sub}
end function
'''
                path.write_text(text)
            body=body.replace(' GetGlobalAA().tasks=[]',' GetGlobalAA().tasks=[]:GetGlobalAA().holderCount=0',1)
            callback='  onApiResult(FixtureEvent(outcome))'
            assert body.count(callback)==1
            delivery='  if outcome.errorCode="compat_prepare_required"\n'+change+'\n  end if\n'+callback
            if duplicate:
                delivery+='\n  if outcome.errorCode="compat_prepare_required" then onApiResult(FixtureEvent(outcome))'
            body=body.replace(callback,delivery,1)
            if prepared is not None:
                encoded=json.dumps(prepared).replace('"','""')
                boundary=' beforeBackTasks=GetGlobalAA().tasks.Count()'
                assert body.count(boundary)==1
                body=body.replace(boundary,' onSiloUICompatResult(FixtureEvent(ParseJson("'+encoded+'")))\n'+boundary,1)
            body=body.replace('print FormatJson({heroCandidateEligible:','''command=invalid
 if m.compatPreparation<>invalid then command=m.compatPreparation.task.command
 print FormatJson({holderCreated:m.compatPreparation<>invalid,holderCount:GetGlobalAA().holderCount,command:command,loading:m.playLoading,audioChoicePresent:m.playAudioChoice<>invalid,versionExplicit:m.playVersionExplicit,normalizedFile:m.playSelectedVersion,acceptedVersions:m.playVersions,audioQueries:SpField(m.fixtureDevice,"audioQueries",[]),heroCandidateEligible:''',1)
            return execute(files,body,root=root)
        with patch.object(scene,'run_brightscript',side_effect=launch):
            return scene.OrdinaryNativeHdr10Scene().scene([detail,started])

    def test_real_auto_play_admits_exact_pair_and_retains_immutable_source_basis(self):
        result=self.scene()
        self.assertTrue(result['holderCreated'],result)
        self.assertEqual(1,result['holderCount'])
        self.assertFalse(result['audioChoicePresent'])
        self.assertFalse(result['versionExplicit'])
        self.assertEqual('',result['normalizedFile'])
        command=result['command']
        self.assertEqual('prepare',command['action'])
        params=command['params']
        self.assertEqual(explicit.KIND,params['eligibilityKind'])
        self.assertIs(True,params.get('autoVersion'))
        self.assertEqual(('731','file:731:audio:1',1),tuple(params[key] for key in ('fileId','audioTrackId','audioTrackIndex')))
        self.assertEqual(self.started['compatContinuation']['autoAudioSelection'],params['autoAudioSelection'])
        self.assertEqual([True,False,False],[track['isDefault'] for track in result['acceptedVersions'][0]['audioTracks']])
        self.assertEqual(['detail','playback_start'],[entry['job']['action'] for entry in result['tasks']])
        queries=result['audioQueries']
        self.assertEqual([('truehd',8,0),('truehd',8,1),('ac3',6,0),('ac3',6,1),('ac3',2,0),('ac3',2,1),('ac3',6,0),('ac3',6,1)],[(q['codec'],q['chcnt'],q['passthru']) for q in queries])
        self.assertTrue(all(q['container']=='mp4' for q in queries))
        for track in params['autoAudioSelection']['basis']['tracks']:
            self.assertEqual({'state':'schema_unpublished','value':None},track['hearing_impaired'])

    def test_actual_owned_prepared_result_emits_auto_bind_with_same_immutable_choice(self):
        entry=self.scene()
        command=entry['command']
        self.assertEqual('prepare',command['action'])
        encoded=json.dumps(command).replace('"','""')
        boundary=' if sceneData<>invalid\n  FixtureSceneStart(sceneData)'
        fixture=auto_holder.P7AutoHolder()
        fixture.choice=copy.deepcopy(self.started['compatContinuation']['autoAudioSelection'])
        close='if m.sceneData=invalid and m.top.result.phase="prepared" then m.top.command={action:"close",commandId:"close-1",holderId:"holder-1",attemptId:"attempt-1",owner:m.owner}'
        owned_close='if m.sceneData=invalid and m.top.result.phase="prepared" then m.top.command={action:"close",commandId:"close-1",holderId:m.top.command.holderId,attemptId:m.top.command.attemptId,owner:m.top.command.owner}'
        transcript=fixture.transcript(overrides={boundary:' m.top.command=ParseJson("'+encoded+'")\n'+boundary,close:owned_close})
        self.assertNotIn('fixtureError',transcript,transcript)
        self.assertEqual('closed',transcript['results'][-1]['phase'])
        self.assertTrue(transcript['results'][-1]['credentialRevoked'])
        prepared=transcript['results'][0]
        self.assertEqual('prepared',prepared['phase'])
        self.assertEqual(command['holderId'],prepared['holderId'])
        self.assertEqual(command['attemptId'],prepared['attemptId'])
        admitted=self.scene(prepared=prepared)
        bind=admitted['command']
        self.assertEqual('bind',bind['action'])
        self.assertIs(True,bind.get('autoVersion'))
        self.assertEqual(command['params']['autoAudioSelection'],bind.get('autoAudioSelection'))
        self.assertEqual((command['holderId'],command['attemptId'],command['owner']),(bind['holderId'],bind['attemptId'],bind['owner']))
        self.assertEqual(2,sum(q['codec']=='truehd' for q in admitted['audioQueries']))
        self.assertEqual(2,sum(q['codec']=='ac3' and q['chcnt']==2 for q in admitted['audioQueries']))

    def test_genuine_profile_preferred_ac3_auto_keeps_raw_truehd_default(self):
        def preferred(wire,decision):
            explicit.fixture(wire,decision)
            wire['versions'][0]['effective_audio_track_index']=1
        detail_job=auto.P7AutoProducer.entry['tasks'][0]['job']
        detail=explicit.task.CompatContinuation().job(enabled=True,scope=detail_job,mutate=preferred,device=explicit.DEVICE)['outcome']
        entry=scene.OrdinaryNativeHdr10Scene().scene([detail])
        job=entry['tasks'][1]['job']
        started=auto.P7AutoProducer().run_auto(job=job,mutate=lambda wire,decision:wire['versions'][0].update(effective_audio_track_index=1))['outcome']
        self.assertEqual('compat_prepare_required',started.get('errorCode'),started)
        result=self.scene(detail=detail,started=started)
        self.assertTrue(result['holderCreated'],result)
        selected=result['command']['params']['autoAudioSelection']
        self.assertEqual(('preferred',1,1),(selected['selection'],selected['preferred_ordinal'],selected['audio_track_index']))
        self.assertEqual([True,False,False],[track['isDefault'] for track in result['acceptedVersions'][0]['audioTracks']])
        self.assertFalse(result['audioChoicePresent'])

    def test_auto_flag_and_kind_are_typed_and_unambiguous(self):
        for value in (None,1,'true',False):
            with self.subTest(flag=value):
                result=self.scene(mutate=lambda result:result['compatContinuation'].update(autoVersion=value))
                self.assertFalse(result['holderCreated'],result)
        def aliased(result):result['compatContinuation']['eligibilitykind']='experimental_query_p8_ts_v1'
        result=self.scene(mutate=aliased)
        self.assertFalse(result['holderCreated'],result)

    def test_missing_null_malformed_or_aliased_choice_never_downgrades(self):
        def missing(c):del c['autoAudioSelection']
        def absent(c):c['autoAudioSelection']=None
        def malformed(c):c['autoAudioSelection']=True
        def alias(c):c['autoaudioselection']=copy.deepcopy(c['autoAudioSelection'])
        def wrong_pair(c):c['autoAudioSelection']['audio_track_index']=2
        for changed in (missing,absent,malformed,alias,wrong_pair):
            with self.subTest(change=changed.__name__):
                result=self.scene(mutate=lambda result:changed(result['compatContinuation']))
                self.assertFalse(result['holderCreated'],result)
                self.assertFalse(result['bound'])
                self.assertEqual(0,result['holderCount'])

    def test_coherent_effective_preference_drift_in_job_or_accepted_version_refuses(self):
        def preferred(wire,decision):
            explicit.fixture(wire,decision)
            wire['versions'][0]['effective_audio_track_index']=1
        detail_job=auto.P7AutoProducer.entry['tasks'][0]['job']
        fresh=explicit.task.CompatContinuation().job(enabled=True,scope=detail_job,mutate=preferred,device=explicit.DEVICE)['outcome']
        self.assertTrue(fresh['ok'],fresh)
        facts=fresh['data']['versions'][0]['autoAudioFacts']
        self.assertEqual({'state':'present','ordinal':1},facts['effective_preference'])
        encoded=json.dumps(facts).replace('"','""')
        changed='ParseJson("'+encoded+'")'
        accepted='m.playVersions=SpCopy(m.playVersions):m.playVersions[0].autoAudioFacts='+changed
        job='''
for each key in m.pending
 child=m.pending[key].task
 if child.job.action="playback_start"
  child.job.params.detail=SpCopy(child.job.params.detail)
  child.job.params.detail.versions[0].autoAudioFacts='''+changed+'''
 end if
end for
'''
        for name,change in (('accepted',accepted),('job',job)):
            with self.subTest(boundary=name):
                result=self.scene(change=change)
                self.assertFalse(result['holderCreated'],result)
                self.assertFalse(result['bound'])

    def test_fresh_mp4_query_drift_refuses_before_holder(self):
        device=dict(explicit.DEVICE)
        key=next(k for k in device if 'format.chcnt' in k)
        device[key]='if format.codec="ac3" and format.chcnt=6 and format.container="mp4" then return {result:false}\n        '+device[key]
        result=self.scene(device=device)
        self.assertFalse(result['holderCreated'],result)
        self.assertFalse(result['bound'])

    def test_selector_presence_and_newer_explicit_play_cannot_reuse_auto_result(self):
        selector='''
for each key in m.pending
 child=m.pending[key].task
 if child.job.action="playback_start" then child.job.params["subtitletrackindex"]=invalid
end for
'''
        result=self.scene(change=selector)
        self.assertFalse(result['holderCreated'],result)
        newer=self.scene(change='PlayItem(m.playItem,0,"731")')
        self.assertFalse(newer['holderCreated'],newer)
        self.assertTrue(newer['loading'])
        self.assertTrue(newer['versionExplicit'])
        self.assertEqual('731',newer['normalizedFile'])
        self.assertEqual(3,len(newer['tasks']))

    def test_duplicate_auto_callback_creates_one_holder(self):
        result=self.scene(duplicate=True)
        self.assertTrue(result['holderCreated'],result)
        self.assertEqual(1,result['holderCount'])


if __name__=='__main__':unittest.main()
