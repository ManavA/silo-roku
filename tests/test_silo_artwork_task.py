"""One existing Task proves exact Silo identity before public metadata IO."""
import copy
import json
from pathlib import Path
import re
import tempfile
import unittest

from tools.brightscript import run_function

CANDIDATE = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parents[1]
SCOPE = {'provider':'silo','sourceId':'silo:https://provider-private.example.test','profileId':'p1','generation':7,'requestId':'app-1'}
OWNER = {'scope':{k:SCOPE[k] for k in ('provider','sourceId','profileId','generation')},'scopeKey':'route-7','key':'native-1','itemId':'native-1','type':'movie','tmdbId':'','identityRequired':True,'nativeType':'movie','artId':1,'readyAtMs':240}
PARAMS = {'type':'movie','itemId':'native-1','itemType':'movie'}
SESSION = {'sourceId':SCOPE['sourceId'],'profileId':'p1','baseUrl':'https://provider-private.example.test','accessToken':'synthetic-access','refreshToken':'synthetic-refresh','profileToken':'synthetic-profile'}
DETAIL = {'content_id':'native-1','type':'movie','tmdb_id':'000141','poster_url':'https://provider-private.example.test/a?token=synthetic','versions':[{'url':'private-route'}]}
META = {'type':'movie','tmdbId':'141','posterPath':'/fixture.jpg','backdropPath':'/fixture.png','private':'synthetic'}
EPISODE_PARAMS = {'type':'tv','itemId':'episode-1','itemType':'episode'}
EPISODE_OWNER = {**OWNER,'itemId':'episode-1','key':'episode-1','type':'tv','nativeType':'episode'}
EPISODE_DETAIL = {'content_id':'episode-1','type':'episode','series_id':'series:1','tmdb_id':'999','title':'Synthetic Episode'}
SERIES_DETAIL = {'content_id':'series:1','type':'series','tmdb_id':'000202','title':'Synthetic Series'}
TV_META = {**META,'type':'tv','tmdbId':'202'}

BOUNDARIES = '''
function MetadataRequestConfig(version as String) as Object
    return {baseUrl:"https://metadata.example",appVersion:version}
end function

function SessionRevision(provider as String) as Integer
    m.revisionReads++
    if m.revisionAtCheck = m.revisionReads then m.revision++
    return m.revision
end function
function LoadSession(provider as String) as Object
    return m.session
end function
function TaskDeviceSession(provider as String, session as Object) as Object
    m.deviceCalls++
    session["deviceId"] = "synthetic-device"
    session["appVersion"] = "0.1.0"
    return session
end function
function ArtworkFixtureClock() as Object
    clock = {elapsed:0,Mark:sub()
        m.elapsed = 0
    end sub,TotalMilliseconds:function() as Integer
        return m.elapsed
    end function}
    m.artworkClock = clock
    return clock
end function
function HttpRequest(request as Object, timeoutMs = 0 as Integer) as Object
    m.requests.Push(request)
    m.timeouts.Push(HttpTimeoutMs(request,timeoutMs))
    index = m.requests.Count()-1
    if index >= m.responses.Count() then return {ok:false,errorCode:"unexpected_request"}
    response = m.responses[index]
    if m.artworkClock <> invalid then m.artworkClock.elapsed += TaskValue(response,"elapsedMs",0)
    if TaskValue(response,"revisionChange",false) then m.revision++
    patch = TaskValue(response,"sessionPatch",{})
    for each key in patch
        m.session[key] = patch[key]
    end for
    result = HttpResponseBody(request,TaskValue(response,"statusCode",200),TaskString(response,"body"))
    if response.DoesExist("okOverride") then result["ok"] = response.okOverride
    return result
end function
function RunSiloArtwork(params as Object, owner as Dynamic, scope as Object, session as Object, responses as Object, revisionAtCheck as Integer) as Object
    m.revision = 1
    m.revisionReads = 0
    m.revisionAtCheck = revisionAtCheck
    m.session = session
    m.responses = responses
    m.requests = []
    m.timeouts = []
    m.artworkClock = invalid
    m.deviceCalls = 0
    job = MergeSessionPatch(scope,{action:"metadata_artwork",params:params,artworkOwner:owner})
    m.top = {job:job,result:invalid}
    runJob()
    return {outcome:m.top.result,requests:m.requests,timeouts:m.timeouts,revision:m.revision,deviceCalls:m.deviceCalls}
end function
'''


class SiloArtworkTaskTests(unittest.TestCase):
    def episode(self, *, detail=None, series=None, metadata=None, responses=None, **kwargs):
        if responses is None:
            responses=[{'body':json.dumps(EPISODE_DETAIL if detail is None else detail),'elapsedMs':500},
                       {'body':json.dumps(SERIES_DETAIL if series is None else series),'elapsedMs':500},
                       {'body':json.dumps(TV_META if metadata is None else metadata),'elapsedMs':500}]
        return self.call(params=EPISODE_PARAMS,owner=EPISODE_OWNER,responses=responses,**kwargs)

    def call(self, *, params=None, owner=None, scope=None, session=None, responses=None, revision_at=0):
        if responses is None:
            responses=[{'body':json.dumps(DETAIL),'elapsedMs':500}, {'body':json.dumps(META),'elapsedMs':500}]
        with tempfile.TemporaryDirectory(prefix='silo_ui-silo-art-task-') as directory:
            temporary=Path(directory)
            worker=temporary/'worker.brs'
            source=(CANDIDATE/'components/ApiTask.brs').read_text()
            source=source.replace('function TaskDeviceSession(', 'function UnusedDeviceSession(',1)
            source=source.replace('CreateObject("roTimespan")','ArtworkFixtureClock()')
            worker.write_text(source)
            http=temporary/'http.brs'
            http_source=(ROOT/'source/network/Http.brs').read_text()
            names=('HttpErrorCode','HttpErrorBodyLimit','HttpErrorBodyWithinLimit','HttpResponseBodyLimit','HttpResponseBody','HttpTimeoutMs')
            http.write_text('\n'.join(re.search(r'(?ms)^function '+name+r'\(.*?^end function',http_source).group(0) for name in names))
            boundary=temporary/'fixture.brs';boundary.write_text(BOUNDARIES)
            files=[CANDIDATE/'components/TaskSiloReplan.brs',CANDIDATE/'source/core/RuntimeIdentity.brs',ROOT/'source/auth/SessionPolicy.brs',ROOT/'source/adapters/PlexAdapter.brs',ROOT/'source/adapters/SiloAdapter.brs',ROOT/'source/adapters/MetadataAdapter.brs',worker,http,boundary]
            return run_function(files,'RunSiloArtwork',[PARAMS if params is None else params,OWNER if owner is None else owner,SCOPE if scope is None else scope,SESSION if session is None else session,responses,revision_at],root=temporary)

    def test_exact_movie_private_detail_then_public_only_dto_in_one_task_budget(self):
        value=self.call()
        self.assertTrue(value['outcome']['ok'])
        self.assertEqual(['https://provider-private.example.test/api/v2/catalog/items/native-1?image_size=medium','https://metadata.example/v1/enrich/movie/141'],[r['url'] for r in value['requests']])
        self.assertEqual([3750,3250],value['timeouts'])
        self.assertEqual([98304,98304],[r['responseBodyLimit'] for r in value['requests']])
        self.assertEqual('Bearer synthetic-access',value['requests'][0]['headers']['Authorization'])
        self.assertEqual('p1',value['requests'][0]['headers']['X-Profile-Id'])
        self.assertNotIn('Authorization',value['requests'][1]['headers'])
        dto=value['outcome']['data']
        self.assertEqual({'type':'movie','tmdbId':'141','posterUri':'https://image.tmdb.org/t/p/w342/fixture.jpg','backdropUri':'https://image.tmdb.org/t/p/w780/fixture.png'},dto)
        self.assertNotIn('private',json.dumps(dto));self.assertNotIn('native-1',json.dumps(dto));self.assertNotIn('viewerRevision',dto)

    def test_episode_uses_exact_fresh_parent_series_then_header_free_tv_metadata(self):
        value=self.episode()
        self.assertTrue(value['outcome']['ok'])
        self.assertEqual(['https://provider-private.example.test/api/v2/catalog/items/episode-1?image_size=medium',
                          'https://provider-private.example.test/api/v2/catalog/items/series%3A1?image_size=medium',
                          'https://metadata.example/v1/enrich/tv/202'],[r['url'] for r in value['requests']])
        self.assertEqual([3750,3250,2750],value['timeouts'])
        self.assertEqual([98304]*3,[r['responseBodyLimit'] for r in value['requests']])
        self.assertEqual(1,value['deviceCalls'])
        for request in value['requests'][:2]:
            self.assertEqual('Bearer synthetic-access',request['headers']['Authorization'])
            self.assertEqual('p1',request['headers']['X-Profile-Id'])
            self.assertEqual('synthetic-device',request['headers']['X-Device-ID'])
        self.assertEqual({'Accept':'application/json','X-Silo-Client':'roku/0.1.0'},value['requests'][2]['headers'])
        self.assertEqual({'type':'tv','tmdbId':'202','posterUri':'https://image.tmdb.org/t/p/w342/fixture.jpg',
                          'backdropUri':'https://image.tmdb.org/t/p/w780/fixture.png'},value['outcome']['data'])
        self.assertNotIn('episode-',json.dumps(value['outcome']['data']));self.assertNotIn('series:',json.dumps(value['outcome']['data']))

    def test_episode_tmdb_is_never_series_identity_or_a_public_lookup_fallback(self):
        for raw in ('999',None,202,{},'private?token=synthetic'):
            value=self.episode(detail={**EPISODE_DETAIL,'tmdb_id':raw})
            self.assertTrue(value['outcome']['ok']);self.assertTrue(value['requests'][-1]['url'].endswith('/tv/202'))
        missing={k:v for k,v in EPISODE_DETAIL.items() if k!='series_id'}
        value=self.episode(detail=missing)
        self.assertFalse(value['outcome']['ok']);self.assertEqual(1,len(value['requests']))

    def test_episode_requires_exact_typed_leaf_and_bounded_opaque_parent_relation(self):
        changes=[{'content_id':'other'},{'content_id':1},{'type':'series'},{'type':'Episode'},
                 {'series_id':None},{'series_id':1},{'series_id':{}},{'series_id':[]},{'series_id':''},
                 {'series_id':'.'},{'series_id':'..'},{'series_id':'../series-1'},
                 {'series_id':' series-1'},{'series_id':'series-1\n'},{'series_id':'x'*257}]
        for change in changes:
            with self.subTest(change=change):
                value=self.episode(detail={**EPISODE_DETAIL,**change})
                self.assertFalse(value['outcome']['ok']);self.assertEqual(1,len(value['requests']))
        for malformed in ('null','[]','"series:1"','not-json'):
            value=self.episode(responses=[{'body':malformed}])
            self.assertFalse(value['outcome']['ok']);self.assertEqual(1,len(value['requests']))

    def test_parent_series_exact_id_type_and_tmdb_proof_precede_public_read(self):
        changes=[{'content_id':'other'},{'content_id':1},{'content_id':' series:1'},{'type':'episode'},
                 {'type':'show'},{'type':'Series'},{'tmdb_id':None},{'tmdb_id':202},{'tmdb_id':'0'},
                 {'tmdb_id':'202?token=synthetic'},{'tmdb_id':'202\n'},{'tmdb_id':'1'*13}]
        for change in changes:
            with self.subTest(change=change):
                value=self.episode(series={**SERIES_DETAIL,**change})
                self.assertFalse(value['outcome']['ok']);self.assertEqual(2,len(value['requests']))
        value=self.episode(responses=[{'body':json.dumps(EPISODE_DETAIL)},{'statusCode':404,'body':'synthetic-error'}])
        self.assertEqual('not_found',value['outcome']['errorCode']);self.assertEqual(2,len(value['requests']))
        for raw in ('null','[]','not-json'):
            value=self.episode(responses=[{'body':json.dumps(EPISODE_DETAIL)},{'body':raw}])
            self.assertFalse(value['outcome']['ok']);self.assertEqual(2,len(value['requests']))

    def test_episode_all_three_reads_recheck_captured_viewer_revision_and_actual_success(self):
        for check,reads in ((2,0),(3,0),(5,1),(7,2),(8,3),(9,3)):
            value=self.episode(revision_at=check)
            self.assertEqual('session_changed',value['outcome']['errorCode']);self.assertEqual(reads,len(value['requests']))
        for stage in range(3):
            for change in ({'revisionChange':True},{'sessionPatch':{'sourceId':'silo:foreign'}},
                           {'sessionPatch':{'profileId':'other'}},{'okOverride':1}):
                responses=[{'body':json.dumps(EPISODE_DETAIL)},{'body':json.dumps(SERIES_DETAIL)},{'body':json.dumps(TV_META)}]
                responses[stage].update(change)
                value=self.episode(responses=responses)
                self.assertFalse(value['outcome']['ok']);self.assertEqual(stage+1,len(value['requests']))

    def test_episode_all_three_receipts_have_same_body_cap_and_cumulative_deadline(self):
        for stage in range(3):
            for body in (' '*98305,'é'*49153):
                responses=[{'body':json.dumps(EPISODE_DETAIL)},{'body':json.dumps(SERIES_DETAIL)},{'body':json.dumps(TV_META)}]
                responses[stage]['body']=body
                value=self.episode(responses=responses)
                self.assertEqual('response_too_large',value['outcome']['errorCode']);self.assertEqual(stage+1,len(value['requests']))
        value=self.episode(responses=[{'body':json.dumps(EPISODE_DETAIL),'elapsedMs':1000},
                                     {'body':json.dumps(SERIES_DETAIL),'elapsedMs':1800},{'body':json.dumps(TV_META)}])
        self.assertEqual('lookup_budget',value['outcome']['errorCode']);self.assertEqual(2,len(value['requests']))
        value=self.episode(responses=[{'body':json.dumps(EPISODE_DETAIL),'elapsedMs':1000},
                                     {'body':json.dumps(SERIES_DETAIL),'elapsedMs':1000},
                                     {'body':json.dumps(TV_META),'elapsedMs':2000}])
        self.assertEqual('lookup_budget',value['outcome']['errorCode']);self.assertEqual([3750,2750,1750],value['timeouts'])

    def test_episode_metadata_must_match_proven_parent_type_and_id_exactly(self):
        for change in ({'type':'movie'},{'tmdbId':'999'},{'tmdbId':'203'}):
            value=self.episode(metadata={**TV_META,**change})
            self.assertEqual('invalid_response',value['outcome']['errorCode']);self.assertEqual(3,len(value['requests']))

    def test_series_maps_to_tv_only_after_fresh_same_series_proof(self):
        params={'type':'tv','itemId':'series-1','itemType':'series'}
        owner={**OWNER,'itemId':'series-1','key':'series-1','type':'tv','nativeType':'series'}
        detail={'content_id':'series-1','type':'series','tmdb_id':'202'}
        metadata={**META,'type':'tv','tmdbId':'202'}
        value=self.call(params=params,owner=owner,responses=[{'body':json.dumps(detail)},{'body':json.dumps(metadata)}])
        self.assertTrue(value['outcome']['ok']);self.assertTrue(value['requests'][1]['url'].endswith('/tv/202'))
        for wire_type in ('episode','show','movie'):
            bad=self.call(params=params,owner=owner,responses=[{'body':json.dumps({**detail,'type':wire_type})}])
            self.assertFalse(bad['outcome']['ok']);self.assertEqual(1,len(bad['requests']))

    def test_exact_content_id_type_and_canonical_tmdb_are_required_before_public_get(self):
        wrong=[{'content_id':'other'},{'content_id':' native-1'},{'content_id':1},{'type':'episode'},{'type':'Movie'},
               {'tmdb_id':''},{'tmdb_id':'0'},{'tmdb_id':141},{'tmdb_id':'141?token=x'},{'tmdb_id':'141\n'},{'tmdb_id':'1234567890123'}]
        for change in wrong:
            with self.subTest(change=change):
                value=self.call(responses=[{'body':json.dumps({**DETAIL,**change})}])
                self.assertFalse(value['outcome']['ok']);self.assertEqual(1,len(value['requests']))

    def test_private_owner_and_source_profile_generation_fences_reject_before_io(self):
        for change in ({'itemId':'other'},{'nativeType':'episode'},{'type':'tv'},{'tmdbId':'141'},{'identityRequired':1},{'artId':0},
                       {'scope':{**OWNER['scope'],'sourceId':'silo:foreign'}},{'scope':{**OWNER['scope'],'profileId':'other'}},
                       {'scope':{**OWNER['scope'],'generation':8}}):
            with self.subTest(change=change):
                value=self.call(owner={**OWNER,**change});self.assertFalse(value['outcome']['ok']);self.assertEqual([],value['requests'])
        value=self.call(scope={**SCOPE,'profileId':'other'});self.assertFalse(value['outcome']['ok']);self.assertEqual([],value['requests'])
        for params in ({**PARAMS,'tmdbId':'141'},{**PARAMS,'itemId':''},{**PARAMS,'itemId':'../native-1'},{**PARAMS,'itemType':'show'}):
            value=self.call(params=params);self.assertFalse(value['outcome']['ok']);self.assertEqual([],value['requests'])

    def test_dot_segment_native_item_ids_are_rejected_before_provider_io(self):
        for identifier in ('.','..'):
            with self.subTest(identifier=identifier):
                value=self.call(params={**PARAMS,'itemId':identifier},owner={**OWNER,'itemId':identifier})
                self.assertFalse(value['outcome']['ok'])
                self.assertEqual([],value['requests'])

    def test_revision_or_viewer_changes_before_and_after_each_get_never_publish(self):
        for check,reads in ((2,0),(3,0),(5,1),(6,2),(7,2)):
            value=self.call(revision_at=check);self.assertFalse(value['outcome']['ok']);self.assertEqual(reads,len(value['requests']))
        for stage in (0,1):
            for change in ({'revisionChange':True},{'sessionPatch':{'sourceId':'silo:foreign'}},{'sessionPatch':{'profileId':'other'}}):
                responses=[{'body':json.dumps(DETAIL)},{'body':json.dumps(META)}]
                responses[stage].update(change)
                value=self.call(responses=responses);self.assertEqual('session_changed',value['outcome']['errorCode']);self.assertEqual(stage+1,len(value['requests']))

    def test_provider_auth_failure_never_refreshes_and_public_identity_mismatch_rejects(self):
        value=self.call(responses=[{'statusCode':401,'body':'synthetic-error'}])
        self.assertEqual('auth_required',value['outcome']['errorCode']);self.assertEqual(1,len(value['requests']))
        for change in ({'type':'tv'},{'tmdbId':'142'}):
            value=self.call(responses=[{'body':json.dumps(DETAIL)},{'body':json.dumps({**META,**change})}])
            self.assertEqual('invalid_response',value['outcome']['errorCode']);self.assertEqual(2,len(value['requests']))

    def test_overall_deadline_and_body_caps_precede_projection(self):
        for stage in (0,1):
            for body in (' '*98305,'é'*49153):
                responses=[{'body':json.dumps(DETAIL)},{'body':json.dumps(META)}]
                responses[stage]['body']=body
                value=self.call(responses=responses);self.assertEqual('response_too_large',value['outcome']['errorCode']);self.assertEqual(stage+1,len(value['requests']))
        for elapsed,expected_reads in ((2800,1),(4000,1)):
            value=self.call(responses=[{'body':json.dumps(DETAIL),'elapsedMs':elapsed},{'body':json.dumps(META)}])
            self.assertEqual('lookup_budget',value['outcome']['errorCode']);self.assertEqual(expected_reads,len(value['requests']))
        value=self.call(responses=[{'body':json.dumps(DETAIL),'elapsedMs':1000},{'body':json.dumps(META),'elapsedMs':3000}])
        self.assertEqual('lookup_budget',value['outcome']['errorCode']);self.assertEqual([3750,2750],value['timeouts'])

    def test_non_boolean_http_success_is_not_identity_proof(self):
        for stage in (0,1):
            responses=[{'body':json.dumps(DETAIL)},{'body':json.dumps(META)}]
            responses[stage]['okOverride']=1
            value=self.call(responses=responses);self.assertFalse(value['outcome']['ok']);self.assertEqual(stage+1,len(value['requests']))

    def test_provider_detail_retains_normal_native_client_headers_but_public_get_does_not(self):
        value=self.call()
        self.assertEqual(1,value['deviceCalls'])
        self.assertEqual('synthetic-device',value['requests'][0]['headers']['X-Device-ID'])
        self.assertEqual('synthetic-device',value['requests'][0]['headers']['X-Silo-Device-Id'])
        self.assertNotIn('X-Device-ID',value['requests'][1]['headers']);self.assertNotIn('X-Silo-Device-Id',value['requests'][1]['headers'])

    def test_existing_public_seed_and_plex_exact_id_path_stays_one_header_free_get(self):
        for provider in ('plex','silo'):
            scope={**SCOPE,'provider':provider,'sourceId':provider+':synthetic'}
            session={**SESSION,'sourceId':scope['sourceId']}
            value=self.call(params={'type':'movie','tmdbId':'141'},scope=scope,session=session,responses=[{'body':json.dumps(META)}])
            self.assertTrue(value['outcome']['ok']);self.assertEqual(1,len(value['requests']));self.assertEqual([4000],value['timeouts'])
            self.assertNotIn('Authorization',value['requests'][0]['headers'])
