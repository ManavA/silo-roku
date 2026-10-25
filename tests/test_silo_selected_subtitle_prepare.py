"""Selected subtitles through real API Task dispatch and SDK/HTTP boundaries."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from tools.brightscript import run_function
from tests import test_silo_playback_task as playback
from tests import test_silo_selected_subtitle_fetch as fetch
from tests.test_silo_selected_subtitle_worker import decision_with_selected
from tests import test_silo_replan_task as replan
from tests.test_silo_selected_subtitle_receipt import selected

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = '''
function TaskDeviceSession(provider as String, session as Object) as Object
    return session
end function
function RunSubtitlePlaybackJob(job as Object, session as Object, responses as Object, scenario as Object) as Object
    m.requests=[]:m.timeouts=[]:m.responses=responses:m.fixtureRevision=0:m.changeRevision=false
    m.fixtureSession=session:m.scenario=scenario:m.fixtureFiles={}:m.fixtureAgent=invalid:m.fixtureDownloads=[]
    device=FixtureSiloDevice():device.videoMode="2160p60"
    m.top={job:job,cancelled:false,result:invalid}
    runJob()
    agent=invalid
    if m.fixtureAgent <> invalid then agent={url:m.fixtureAgent.url,headers:m.fixtureAgent.headers}
    files=[]
    for each path in m.fixtureFiles
        files.Push(path)
    end for
    binding=SiloUISubtitleBinding(m.top.result.plan,job.generation,job.requestId)
    return {outcome:m.top.result,binding:binding,requests:m.requests,agent:agent,files:files,downloads:m.fixtureDownloads}
end function
'''


class SelectedSubtitlePreparationTests(unittest.TestCase):
    def run_job(self, *, scenario=None, decision=None, job_override=None, responses_override=None, session_override=None, recovery_clock=False):
        session=playback.SiloPlaybackTaskTests().session()
        job={'provider':'silo','action':'playback_start','sourceId':session['sourceId'],
             'profileId':session['profileId'],'generation':7,'requestId':12,
             'params':{'itemId':'fixture-item','fileId':'f1','startPositionMs':0}}
        if session_override is not None: session=session_override
        if job_override is not None: job=job_override
        cap=json.loads((ROOT/'tests/fixtures/silo/playback_capabilities.json').read_text())
        cap['installation_id']='server-install'
        responses=[{'statusCode':200,'body':json.dumps(cap)},
                   {'statusCode':200,'body':json.dumps(decision_with_selected() if decision is None else decision)}]
        if responses_override is not None: responses=responses_override
        with tempfile.TemporaryDirectory(prefix='silo_ui-subtitle-job-') as directory:
            t=Path(directory)
            api=t/'api.brs'
            api.write_text((ROOT/'components/ApiTask.brs').read_text().replace(
                'function TaskDeviceSession(','function UnusedTaskDeviceSession(',1).replace(
                'function TaskUniqueId(','function UnusedTaskUniqueId(',1).replace(
                'function TaskRokuSiloContext(','function UnusedTaskRokuSiloContext(',1).replace(
                'CreateObject("roDeviceInfo")','FixtureSiloDevice()'))
            http=t/'http.brs'
            http.write_text((ROOT/'source/network/Http.brs').read_text().replace(
                'function HttpRequest(','function UnusedHttpRequest(',1))
            helper=t/'fetch.brs';code=fetch.HELPER.read_text()
            for name in ('SiloSubtitleClock','SiloSubtitleUuid','SiloSubtitleFileSystem',
                         'SiloSubtitleRead','SiloSubtitleNewPort','SiloSubtitleNewTransfer',
                         'SiloSubtitleWait','SiloSubtitleEventType'):
                code=code.replace('function '+name+'(','function Unused'+name+'(',1)
            helper.write_text(code)
            boundary=t/'boundary.brs'
            sdk=fetch.SDK_BOUNDARIES.replace('function LoadSession(', 'function UnusedSdkLoadSession(',1).replace(
                'function SessionRevision(', 'function UnusedSdkSessionRevision(',1)
            http_boundary=playback.BOUNDARIES
            wrapper=WRAPPER
            if recovery_clock:
                http_boundary=http_boundary.replace('response = m.responses.Shift()', 'response = m.responses.Shift()\n    m.fixtureRecoveryElapsed=m.fixtureRecoveryElapsed+TaskValue(response,"elapsedMs",0)')
                wrapper=wrapper.replace('m.requests=[]:m.timeouts=[]', 'm.fixtureRecoveryElapsed=0:m.requests=[]:m.timeouts=[]')
                wrapper=wrapper.replace('device=FixtureSiloDevice()', 'if scenario.keepFile=true then m.fixtureFiles["tmp:/silo-subtitle-11111111-1111-4111-8111-111111111111.vtt"]={size:12,body:"unrelated"}\n    device=FixtureSiloDevice()')
                wrapper += '''
function FixtureRecoveryClock() as Object
    return {owner:m,fired:false,Mark:sub()
        m.owner.fixtureRecoveryElapsed=0
    end sub,TotalMilliseconds:function() as Integer
        final="tmp:/silo-subtitle-00000000-0000-4000-8000-000000000001.srt"
        if m.owner.fixtureFiles.DoesExist(final) and not m.fired
            m.fired=true
            m.owner.fixtureRecoveryElapsed=m.owner.fixtureRecoveryElapsed+TaskValue(m.owner.scenario,"publicationDelayMs",0)
            if m.owner.scenario.cancelBeforePublication=true then m.owner.top.cancelled=true
            if m.owner.scenario.revisionBeforePublication=true then m.owner.fixtureRevision=m.owner.fixtureRevision+1
            if m.owner.scenario.profileBeforePublication=true then m.owner.fixtureSession["profileToken"]="changed"
        end if
        return m.owner.fixtureRecoveryElapsed
    end function}
end function
'''
            boundary.write_text(http_boundary+sdk+wrapper)
            files=[]
            for source in playback.FILES:
                if source.name=='TaskSiloReplan.brs':
                    local=t/source.name
                    code=source.read_text().replace('CreateObject("roDeviceInfo")','FixtureSiloDevice()')
                    if recovery_clock:code=code.replace('CreateObject("roTimespan")','FixtureRecoveryClock()')
                    local.write_text(code)
                    files.append(local)
                else: files.append(source)
            return run_function([*files,ROOT/'source/core/SiloUIPlaybackChoicesPolicy.brs',ROOT/'components/SiloUISubtitleArtifact.brs',http,api,helper,boundary],
                                'RunSubtitlePlaybackJob',[job,session,responses,scenario or {}],root=t)

    def test_successful_start_publishes_only_ready_local_selected_subtitle(self):
        result=self.run_job()
        self.assertTrue(result['outcome']['ok'],result)
        plan=result['outcome']['plan']
        self.assertEqual('sidecar_ready',plan['selectedSubtitle']['kind'])
        self.assertTrue(plan['selectedSubtitle']['renderingReady'])
        artifact=plan['subtitleArtifact']
        self.assertEqual([artifact['uri']],result['files'])
        self.assertEqual((7,12,'f1',1),tuple(artifact['owner'][k] for k in ('generation','requestId','fileId','selectedOrdinal')))
        self.assertEqual({'Authorization':'Bearer synthetic-access-token'},result['agent']['headers'])
        self.assertNotIn('/subtitles/',json.dumps(plan))
        self.assertNotIn('privateArtifact',json.dumps(plan))

    def test_actual_worker_artifact_binds_without_a_json_roundtrip(self):
        result=self.run_job()
        self.assertTrue(result['outcome']['ok'],result)
        self.assertIsNotNone(result['binding'],result)
        self.assertEqual(result['outcome']['plan']['subtitleArtifact']['uri'],result['binding']['uri'])

    def test_incomplete_optional_playback_context_keeps_video_without_fetching(self):
        decision=decision_with_selected()
        del decision['playback_plan']['available_qualities']
        result=self.run_job(decision=decision)
        self.assertTrue(result['outcome']['ok'],result)
        self.assertNotIn('siloPlayback',result['outcome']['plan'])
        self.assertEqual('unsupported',result['outcome']['plan']['selectedSubtitle']['kind'])
        self.assertNotIn('subtitleArtifact',result['outcome']['plan'])
        self.assertEqual([],result['files'])
        self.assertEqual([],result['downloads'])

    def test_optional_download_failure_preserves_valid_video_and_cleanup_identity(self):
        for scenario in ({'status':404},{'cancelOnWait':True},{'noEvent':True}):
            with self.subTest(scenario=scenario):
                result=self.run_job(scenario=scenario)
                self.assertTrue(result['outcome']['ok'],result)
                plan=result['outcome']['plan']
                self.assertEqual('sess-1',plan['sessionId'])
                self.assertEqual('f1',plan['versionId'])
                self.assertEqual('fetch_failed',plan['selectedSubtitle']['kind'])
                self.assertFalse(plan['selectedSubtitle']['renderingReady'])
                self.assertNotIn('subtitleArtifact',plan)
                self.assertEqual([],result['files'])

    def test_replan_fetches_the_new_plan_artifact_with_current_request_owner(self):
        params=replan.SiloReplanTaskTests().params()
        params['plan']['siloPlayback']['selectedTracks']['subtitle']={'id':'file:f1:subtitle:1','index':1}
        decision=decision_with_selected('session-0001')
        decision['session_id']='session-0001'
        decision['playback_plan'].update(plan_id='plan-0002',plan_attempt_key='plan-key-0002')
        session={'baseUrl':'https://silo.example','sourceId':'silo:synthetic','profileId':'owner',
                 'deviceId':'fixture-device','accessToken':'synthetic-access','profileToken':'synthetic-profile'}
        job={'provider':'silo','action':'playback_replan','sourceId':session['sourceId'],
             'profileId':session['profileId'],'generation':7,'requestId':13,'params':params}
        cap=json.loads((ROOT/'tests/fixtures/silo/playback_capabilities.json').read_text())
        cap['installation_id']='install-0001'
        result=self.run_job(job_override=job,session_override=session,responses_override=[
            {'statusCode':200,'body':json.dumps(cap)},{'statusCode':200,'body':json.dumps(decision)}])
        self.assertTrue(result['outcome']['ok'],result)
        plan=result['outcome']['plan']
        self.assertEqual('sidecar_ready',plan['selectedSubtitle']['kind'])
        self.assertEqual('plan-key-0002',plan['subtitleArtifact']['owner']['planAttemptKey'])
        self.assertEqual(13,plan['subtitleArtifact']['owner']['requestId'])
        self.assertIn('/session-0001/subtitles/1.vtt?',result['agent']['url'])

    def test_automatic_audio_replan_downloads_only_the_final_selected_artifact(self):
        class CaptureScenario(playback.SiloPlaybackTaskTests):
            def worker(self, function, arguments, **kwargs):
                if function=='RunSiloNativeBestStart': return arguments
                return super().worker(function,arguments,**kwargs)
        session,params,responses,*_=CaptureScenario().native_best_start(compatible_audio=True)
        selected_plans=[]
        for response in responses:
            raw=json.loads(response['body'])
            if 'playback_plan' not in raw: continue
            plan=raw['playback_plan']
            receipt=selected(file_id='f2',session=raw['session_id'])
            plan['subtitle']=receipt['subtitle']
            plan['selected_tracks']['subtitle']=receipt['selected_tracks']['subtitle']
            selected_plans.append((response,raw))
        final_response,final=selected_plans[-1]
        final_plan=final['playback_plan']
        final_url=final_plan['subtitle']['artifact']['url']+'&external_subtitle_key='+'a'*64
        final_plan['subtitle']['artifact']['url']=final_url
        final_plan['subtitle']['inventory'][1]['url']=final_url
        for response,raw in selected_plans: response['body']=json.dumps(raw)
        job={'provider':'silo','action':'playback_start','sourceId':session['sourceId'],
             'profileId':session['profileId'],'generation':7,'requestId':12,'params':params}
        result=self.run_job(job_override=job,session_override=session,responses_override=responses)
        self.assertTrue(result['outcome']['ok'],result)
        plan=result['outcome']['plan']
        self.assertEqual('sidecar_ready',plan['selectedSubtitle']['kind'])
        self.assertEqual('plan-key-0002',plan['subtitleArtifact']['owner']['planAttemptKey'])
        self.assertEqual(1,plan['subtitleArtifact']['owner']['selectedOrdinal'])
        self.assertEqual(1,len(result['downloads']))
        self.assertIn('external_subtitle_key='+'a'*64,result['downloads'][0]['url'])
        self.assertEqual([plan['subtitleArtifact']['uri']],result['files'])


if __name__=='__main__':
    unittest.main()
