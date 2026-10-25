"""Optional inference is captured once and expires across queue and playback changes."""
from pathlib import Path
import tempfile
import unittest
from tools.brightscript import run_function

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / 'source/core/StillWatchingPolicy.brs'
SCOPE = dict(provider='plex', sourceId='plex:fixture', profileId='owner', generation=7)
PREF = dict(schemaVersion=1, sourceId='plex:fixture', profileId='owner', personalized=True,
            cloudDecisions=True, stillWatchingCheck=True, gatewayOrigin='https://fixture.example.test')
VIEWER = dict(daypart='evening', weekend=False, device='tv', session=dict(minutes=17, episodes_in_row=3))
HARNESS = '''
function SwViewerCases(cases as Object) as Object
    out=[]
    for each value in cases
        out.Push(StillWatchingViewer(value.hour,value.day,value.elapsed,value.streak))
    end for
    return out
end function
function SwNativeCases(scope as Object,pref as Object,viewer as Object,cases as Object) as Object
    owner=SwFixtureOwner(scope)
    capture=StillWatchingCapture(owner,pref,1800000000123#,9500,viewer)
    out=[]
    for each entry in cases
        native={attemptId:"play-1",mode:"playback",state:"playing",clipId:7,renderedClipId:7,
            renderedEpoch:0,errorCode:0,renderedPosition:1100}
        for each field in entry
            native[field]=entry[field]
        end for
        out.Push(StillWatchingNativeMatches(capture,native))
    end for
    return out
end function
function SwFixtureOwner(scope as Object) as Object
    return {scope:scope,attemptId:"play-1",versionId:"file-1",itemId:"101",lookupId:"upnext-1",
        phase:"watching",asked:true,stillWatching:false,dismissed:false,landed:true,settling:false,
        clipId:7,renderedEpoch:0,renderedMs:1100000,durationMs:1200000,promptMs:1090000,targetMs:1120000,
        forced:false,autoplayAllowed:true,autoplayStreak:3,nativeState:"playing",focus:"play",
        next:{itemId:"102",title:"Next"},previous:invalid}
end function
function SwFixtureJob(state as Object) as Object
    job=MpCopy(state.scope)
    job.action="still_watching":job.requestId="app-4"
    job.params=StillWatchingParams(state)
    job.stillWatchingOwner=StillWatchingOwner(state)
    return job
end function
function SwFixtureTrace(scope as Object,pref as Object,viewer as Object,cases as Object) as Object
    traces=[]
    for each entry in cases
        owner=SwFixtureOwner(scope)
        currentPref=MpCopy(pref)
        capture=StillWatchingCapture(owner,pref,1800000000123#,9500,viewer)
        if entry.kind="capture"
            if entry.DoesExist("preference") then currentPref=entry.preference
            for each field in MpField(entry,"owner",{})
                owner[field]=entry.owner[field]
            end for
            try
                capture=StillWatchingCapture(owner,currentPref,MpField(entry,"epoch",1800000000123#),MpField(entry,"mono",9500),viewer)
            catch failure
                capture={threw:true}
            end try
            traces.Push(capture)
        else
            job=SwFixtureJob(capture)
            if entry.kind="bind"
                for each field in MpField(entry,"job",{})
                    job[field]=entry.job[field]
                end for
                traces.Push(StillWatchingBind(capture,job))
            else
                capture=StillWatchingBind(capture,job)
                for each field in MpField(entry,"owner",{})
                    owner[field]=entry.owner[field]
                end for
                if entry.DoesExist("preference") then currentPref=entry.preference
                if entry.DoesExist("pendingJob") then job=entry.pendingJob
                result=MpCopy(scope)
                result.action="still_watching":result.requestId="app-4":result.ok=true
                result.data={probability:MpField(entry,"probability",.2)}
                for each field in MpField(entry,"result",{})
                    result[field]=entry.result[field]
                end for
                epoch=MpField(entry,"epoch",1800000000922#)
                if entry.DoesExist("epochDelta") then epoch=1800000000123#+entry.epochDelta
                output=StillWatchingResult(capture,owner,currentPref,job,result,
                    epoch,MpField(entry,"mono",10299))
                repeated=StillWatchingResult(output.state,owner,currentPref,job,result,1800000000922#,10299)
                traces.Push({output:output,repeated:repeated})
            end if
        end if
    end for
    return traces
end function
'''


class StillWatchingPolicyTests(unittest.TestCase):
    def test_current_native_witness_requires_typed_matching_clip_epoch_and_error_free_playback(self):
        self.assertTrue('function StillWatchingNativeMatches(' in POLICY.read_text(),'current native inference witness missing')
        changes=[{},dict(state='paused'),dict(attemptId='play-2'),dict(mode='preview'),dict(state='finished'),
                 dict(clipId=8),dict(renderedClipId=8),dict(renderedEpoch=1),dict(renderedEpoch=False),
                 dict(errorCode=-3),dict(errorCode=False),dict(renderedPosition=-1),dict(renderedPosition='1100')]
        with tempfile.TemporaryDirectory(prefix='silo-still-native-') as directory:
            path=Path(directory)/'fixture.brs';path.write_text(HARNESS)
            files=[ROOT/'source/core/ServerUrlPolicy.brs',ROOT/'source/core/MarkerPolicy.brs',
                   ROOT/'source/core/UpNextPolicy.brs',POLICY,path]
            out=run_function(files,'SwNativeCases',[SCOPE,PREF,VIEWER,changes],root=path.parent)
        self.assertEqual([True,True]+[False]*11,out)

    def test_viewer_projects_only_android_local_daypart_weekend_and_session_counters(self):
        self.assertTrue('function StillWatchingViewer(' in POLICY.read_text(),'local coarse viewer projection missing')
        cases=[dict(hour=hour,day=day,elapsed=1079999,streak=3) for hour,day in
               ((0,0),(4,1),(5,2),(10,3),(11,4),(16,5),(17,6),(21,0),(22,1),(23,2))]
        with tempfile.TemporaryDirectory(prefix='silo-still-viewer-') as directory:
            path=Path(directory)/'fixture.brs';path.write_text(HARNESS)
            out=run_function([ROOT/'source/core/MarkerPolicy.brs',POLICY,path],'SwViewerCases',[cases],root=path.parent)
        self.assertEqual(['late','late','morning','morning','day','day','evening','evening','late','late'],[x['daypart'] for x in out])
        for case,result in zip(cases,out):
            self.assertEqual({'daypart','weekend','device','session'},set(result))
            self.assertEqual(case['day'] in (0,6),result['weekend'])
            self.assertEqual(dict(minutes=17,episodes_in_row=3),result['session'])

    def run_cases(self, cases, viewer=None):
        self.assertTrue(POLICY.exists(), 'captured optional decision policy missing')
        with tempfile.TemporaryDirectory(prefix='silo-still-watching-') as directory:
            path=Path(directory)/'fixture.brs';path.write_text(HARNESS)
            files=[ROOT/'source/core/ServerUrlPolicy.brs',
                   ROOT/'source/core/MarkerPolicy.brs',ROOT/'source/core/UpNextPolicy.brs',POLICY,path]
            return run_function(files,'SwFixtureTrace',[SCOPE,PREF,viewer or VIEWER,cases],root=path.parent)

    def test_capture_keeps_subsecond_epoch_and_total_800ms_deadline(self):
        out=self.run_cases([dict(kind='capture')])[0]
        self.assertEqual((1800000000123,1800000000923,9500,10300),
                         (out['requestedAtMs'],out['deadlineMs'],out['requestedMonoMs'],out['deadlineMonoMs']))
        self.assertEqual(VIEWER,out['viewer']);self.assertEqual('',out['requestId'])

    def test_capture_requires_enabled_confirmed_preferences_and_visible_rendered_owner(self):
        cases=[]
        for field in ('personalized','cloudDecisions','stillWatchingCheck'):
            for value in (False,'true',1,None):
                cases.append(dict(kind='capture',preference={**PREF,field:value}))
        for field,value in [('phase','closing'),('asked',False),('dismissed',True),('settling',True),
                            ('landed',False),('renderedEpoch',1),('clipId',7.5),('nativeState','finished'),
                            ('renderedMs',1000),('stillWatching',True)]:
            cases.append(dict(kind='capture',owner={field:value}))
        self.assertTrue(all(value is None for value in self.run_cases(cases)))

    def test_invalid_epoch_and_monotonic_values_are_rejected_without_32bit_conversion(self):
        cases=[dict(kind='capture',**{field:value}) for field in ('epoch','mono')
               for value in (True,'9500',None,-1,9500.5,1e100)]
        self.assertTrue(all(value is None for value in self.run_cases(cases)))

    def test_owner_boolean_and_rendered_epoch_fields_require_actual_types(self):
        cases=[dict(kind='capture',owner={field:value}) for field,value in (
            ('dismissed','false'),('settling',0),('renderedEpoch',False),
            ('stillWatching','false'),('autoplayAllowed',False),('autoplayStreak','3'))]
        self.assertTrue(all(value is None for value in self.run_cases(cases)))

    def test_binding_requires_actual_admitted_request_and_exact_public_params(self):
        jobs=[{},dict(action='detail'),dict(requestId=''),dict(profileId='other'),
              dict(params={}),dict(stillWatchingOwner={})]
        out=self.run_cases([dict(kind='bind',job=job) for job in jobs])
        self.assertEqual('app-4',out[0]['requestId']);self.assertTrue(all(value is None for value in out[1:]))

    def test_valid_reply_is_single_use_for_low_and_high_probabilities(self):
        out=self.run_cases([dict(kind='result',probability=value) for value in (0,.2,.8,1)])
        for value,result in zip((0,.2,.8,1),out):
            self.assertEqual(value,result['output']['probability'])
            self.assertTrue(result['output']['state']['consumed'])
            self.assertIsNone(result['repeated']['probability'])

    def test_either_clock_expiry_or_rollback_rejects_the_response(self):
        cases=[dict(kind='result',mono=value) for value in (10300,11000,9499)]
        cases += [dict(kind='result',epochDelta=value) for value in (800,1000,-1)]
        self.assertTrue(all(value['output']['probability'] is None for value in self.run_cases(cases)))

    def test_changed_episode_clip_scope_preferences_or_finished_owner_cannot_accept(self):
        changes=[dict(attemptId='play-2'),dict(versionId='file-2'),dict(itemId='102'),dict(clipId=8),
                 dict(renderedEpoch=1),dict(scope={**SCOPE,'generation':8}),dict(scope={**SCOPE,'profileId':'other'}),
                 dict(nativeState='finished'),dict(settling=True),dict(dismissed=True)]
        cases=[dict(kind='result',owner=owner) for owner in changes]
        cases += [dict(kind='result',preference={**PREF,'cloudDecisions':False}),
                  dict(kind='result',preference={**PREF,'gatewayOrigin':'https://other.example.test'})]
        self.assertTrue(all(value['output']['probability'] is None for value in self.run_cases(cases)))

    def test_malformed_or_unmatched_results_never_become_inference(self):
        cases=[dict(kind='result',probability=value) for value in (True,'0.1',None,-.1,1.1,1e100)]
        cases += [dict(kind='result',result=result) for result in (
            dict(ok='true'),dict(ok=False),dict(requestId='app-5'),dict(action='detail'),
            dict(profileId='other'),dict(data={}),dict(data={'probability':.1,'token':'synthetic-private'}))]
        self.assertTrue(all(value['output']['probability'] is None for value in self.run_cases(cases)))


if __name__=='__main__':unittest.main()
