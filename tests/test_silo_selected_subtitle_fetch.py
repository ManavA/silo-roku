"""Selected sidecar fetch policy and Task boundary behavior with fake file/HTTP seams."""
import copy
import tempfile
import unittest
from pathlib import Path

from tools.brightscript import run_function
from tests.test_silo_selected_subtitle_receipt import selected, BASE

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / 'source/core/SiloPlaybackPolicy.brs'
ADAPTER = ROOT / 'source/adapters/SiloAdapter.brs'
HELPER = ROOT / 'components/TaskSiloSubtitleFetch.brs'
SESSION = {'baseUrl': BASE, 'accessToken': 'fake-access-only',
           'sourceId': 'silo:test', 'profileId': 'p1'}
OWNER = {'sourceId': 'silo:test', 'profileId': 'p1', 'generation': 7,
         'requestId': 12, 'sessionRevision': 3, 'sessionId': 'session-0001',
         'planAttemptKey': 'attempt-1', 'fileId': '42', 'selectedOrdinal': 1,
         'timelineOffsetMs': 0}


def receipt(plan=None):
    return run_function([POLICY, ADAPTER], 'SiloSelectedSubtitleReceipt',
                        [selected() if plan is None else plan, BASE, OWNER['sessionId']])


class FetchPlanTests(unittest.TestCase):
    def plan(self, source=None, session=None, owner=None):
        self.assertTrue(HELPER.is_file(), 'real Task fetch helper is missing')
        return run_function([POLICY, ADAPTER, HELPER], 'SiloSubtitleFetchPlan',
                            [receipt() if source is None else source,
                             SESSION if session is None else session,
                             OWNER if owner is None else owner])

    def test_exact_private_receipt_and_owner_admit_only_bearer_transport(self):
        result = self.plan()
        self.assertTrue(result['ok'], result)
        self.assertEqual('https://silo.example/api/v2/stream/session-0001/subtitles/1.vtt?file_id=42', result['url'])
        self.assertEqual('fake-access-only', result['token'])
        self.assertEqual(('vtt', 'text/vtt', 0),
                         (result['format'], result['mimeType'], result['timingOriginSeconds']))
        self.assertNotIn('X-Profile', str(result))

    def test_receipt_session_file_ordinal_and_origin_must_remain_exact(self):
        valid = receipt()
        cases = []
        for key, value in (('sessionId', 'other'), ('fileId', '99'), ('selectedOrdinal', 0),
                           ('profileId', 'other'), ('sourceId', 'silo:other')):
            owner = dict(OWNER, **{key: value})
            cases.append((valid, SESSION, owner))
        wrong = copy.deepcopy(valid)
        wrong['privateArtifact']['url'] = 'https://foreign.example/api/v2/stream/session-0001/subtitles/1.vtt?file_id=42'
        cases.append((wrong, SESSION, OWNER))
        wrong = copy.deepcopy(valid)
        wrong['privateArtifact']['url'] = 'https://silo.example/api/v2/stream/session-0001/subtitles/0.vtt?file_id=42'
        cases.append((wrong, SESSION, OWNER))
        wrong = copy.deepcopy(valid)
        wrong['public']['kind'] = 'off'
        cases.append((wrong, SESSION, OWNER))
        for candidate, session, owner in cases:
            with self.subTest(owner=owner, receipt=candidate['public']['kind']):
                self.assertFalse(self.plan(candidate, session, owner)['ok'])

    def test_missing_bearer_or_bad_owner_never_admits_io(self):
        for session in (dict(SESSION, accessToken=''), dict(SESSION, accessToken='bad\nheader')):
            self.assertFalse(self.plan(session=session)['ok'])
        for owner in (dict(OWNER, requestId=-1), dict(OWNER, sessionRevision=-1),
                      dict(OWNER, planAttemptKey=''), dict(OWNER, selectedOrdinal=True)):
            self.assertFalse(self.plan(owner=owner)['ok'])

    def test_only_documented_query_fields_and_one_timing_replacement(self):
        for query in ('file_id=42&api_key=canary', 'file_id=42&Authorization=canary',
                      'file_id=42&downloaded_subtitle_id=7&downloaded_subtitle_id=8',
                      'file_id=42&%74imestamp_offset=2'):
            raw = selected()
            url = '/api/v2/stream/session-0001/subtitles/1.vtt?' + query
            raw['subtitle']['artifact']['url'] = url
            raw['subtitle']['inventory'][1]['url'] = url
            candidate = receipt(raw)
            self.assertTrue(candidate['ok'], candidate)
            self.assertFalse(self.plan(source=candidate)['ok'])

        raw = selected()
        url = '/api/v2/stream/session-0001/subtitles/1.vtt?file_id=42&timestamp_offset=2&embedded_stream_index=3'
        raw['subtitle']['artifact']['url'] = url
        raw['subtitle']['inventory'][1]['url'] = url
        planned = self.plan(source=receipt(raw), owner=dict(OWNER, timelineOffsetMs=10250))
        self.assertTrue(planned['ok'], planned)
        self.assertEqual('https://silo.example/api/v2/stream/session-0001/subtitles/1.vtt?file_id=42&embedded_stream_index=3&timestamp_offset=-10.25', planned['url'])
        self.assertNotIn('timestamp_offset', self.plan()['url'])

    def test_nonzero_rebased_srt_is_unsupported(self):
        raw = selected()
        raw['subtitle']['artifact'].update(url='/api/v2/stream/session-0001/subtitles/1.srt?file_id=42&original=1',
                                          format='srt', mime_type='application/x-subrip')
        raw['subtitle']['inventory'][1]['url'] = raw['subtitle']['artifact']['url']
        candidate = receipt(raw)
        self.assertTrue(candidate['ok'], candidate)
        self.assertEqual('subtitle_timing_unsupported', self.plan(candidate, owner=dict(OWNER,timelineOffsetMs=10000))['errorCode'])


if __name__ == '__main__':
    unittest.main()

class SubtitleSignatureTests(unittest.TestCase):
    def test_bounded_text_signatures_accept_vtt_and_srt_not_html(self):
        cases = (('WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nCue', 'vtt', True),
                 ('WEBVTT-not-real\n\n00:00:00.000 --> 00:00:01.000', 'vtt', False),
                 ('1\n00:00:00,000 --> 00:00:01,000\nCue\n', 'srt', True),
                 ('<html><body>error</body></html>', 'srt', False),
                 ('WEBVTT\n\n00:00:00.000 --> 00:00:01.000', 'srt', False))
        for body, fmt, expected in cases:
            with self.subTest(fmt=fmt, body=body[:8]):
                self.assertEqual(expected, run_function([POLICY, ADAPTER, HELPER],
                    'SiloSubtitleTextSignature', [body, fmt]))

    def test_srt_receipt_remains_eligible(self):
        raw = selected()
        raw['subtitle']['artifact'].update(url='/api/v2/stream/session-0001/subtitles/1.srt?file_id=42',
                                          format='srt', mime_type='application/x-subrip')
        raw['subtitle']['inventory'][1]['url'] = raw['subtitle']['artifact']['url']
        candidate = receipt(raw)
        self.assertTrue(candidate['ok'], candidate)
        planned = run_function([POLICY, ADAPTER, HELPER], 'SiloSubtitleFetchPlan',
                               [candidate, SESSION, OWNER])
        self.assertTrue(planned['ok'], planned)
        self.assertEqual('srt', planned['format'])

SDK_BOUNDARIES = '''
function SessionRevision(provider as String) as Integer
    return m.fixtureRevision
end function
function LoadSession(provider as String) as Object
    return m.fixtureSession
end function
function SiloSubtitleClock() as Object
    m.fixtureClock = {elapsed:0,Mark:sub()
        m.elapsed = 0
    end sub,TotalMilliseconds:function() as Integer
        return m.elapsed
    end function}
    return m.fixtureClock
end function
function SiloSubtitleUuid() as String
    return "00000000-0000-4000-8000-000000000001"
end function
function SiloSubtitleFileSystem() as Object
    return {files:m.fixtureFiles,renameOK:m.scenario.renameOK,renameThrows:m.scenario.throwOnRename,missingInvalid:m.scenario.missingInvalid,
        Stat:function(path as String) as Dynamic
            if m.files.DoesExist(path) then return m.files[path]
            if m.missingInvalid = true then return invalid
            return {}
        end function,
        Delete:function(path as String) as Boolean
            m.files.Delete(path)
            return true
        end function,
        Rename:function(old as String, new as String) as Boolean
            if m.renameThrows = true then throw "private-rename-detail"
            if m.renameOK = false then return false
            if not m.files.DoesExist(old) then return false
            m.files[new] = m.files[old]
            m.files.Delete(old)
            return true
        end function}
end function
function SiloSubtitleRead(path as String) as String
    if not m.fixtureFiles.DoesExist(path) then return ""
    return m.fixtureFiles[path].body
end function
function SiloSubtitleNewPort() as Object
    return {}
end function
function SiloSubtitleNewTransfer() as Object
    m.fixtureAgent = {headers:{},cancelled:false,cert:"",peer:false,host:false,
        files:m.fixtureFiles,scenario:m.scenario,downloads:m.fixtureDownloads,
        SetMessagePort:sub(port as Object)
        end sub,
        SetUrl:sub(url as String)
            m.url = url
        end sub,
        RetainBodyOnError:function(value as Boolean) as Boolean
            return true
        end function,
        SetCertificatesFile:function(value as String) as Boolean
            m.cert = value
            return true
        end function,
        EnablePeerVerification:function(value as Boolean) as Boolean
            m.peer = value
            return true
        end function,
        EnableHostVerification:function(value as Boolean) as Boolean
            m.host = value
            return true
        end function,
        AddHeader:function(name as String, value as String) as Boolean
            m.headers[name] = value
            return true
        end function,
        AsyncGetToFile:function(path as String) as Boolean
            m.path = path
            m.downloads.Push({url:m.url,headers:m.headers})
            body = m.scenario.body
            if type(body) <> "String" then body = "WEBVTT" + Chr(10) + Chr(10) + "00:00:00.000 --> 00:00:01.000" + Chr(10) + "Cue"
            size = Len(body)
            if m.scenario.DoesExist("size") then size = m.scenario.size
            m.files[path] = {size:size,body:body}
            return true
        end function,
        AsyncCancel:function() as Boolean
            m.cancelled = true
            return true
        end function,
        GetIdentity:function() as Integer
            return 1
        end function}
    return m.fixtureAgent
end function
function SiloSubtitleWait(port as Object) as Dynamic
    m.fixtureClock.elapsed += 100
    if m.scenario.DoesExist("throwOnWait") then throw "private-network-detail"
    if m.scenario.DoesExist("cancelOnWait") then m.top.cancelled = true
    if m.scenario.DoesExist("revisionOnWait") then m.fixtureRevision = 4
    if m.scenario.DoesExist("noEvent") then return invalid
    status = 200
    if m.scenario.DoesExist("status") then status = m.scenario.status
    headers = {"Content-Type":"text/vtt; charset=utf-8"}
    if m.scenario.DoesExist("headers") then headers = m.scenario.headers
    return {status:status,headers:headers,
        GetSourceIdentity:function() as Integer
            return 1
        end function,
        GetResponseCode:function() as Integer
            return m.status
        end function,
        GetResponseHeaders:function() as Object
            return m.headers
        end function}
end function
function SiloSubtitleEventType(event as Dynamic) as String
    if type(event) = "roAssociativeArray" then return "roUrlEvent"
    return type(event)
end function
function RunSubtitleSdkFixture(receipt as Object, session as Object, owner as Object, scenario as Object) as Object
    m.scenario = scenario:m.fixtureSession = session:m.fixtureRevision = 3
    m.fixtureFiles = {}:m.fixtureAgent = invalid:m.fixtureDownloads = []
    if scenario.occupied = true then m.fixtureFiles["tmp:/silo-subtitle-00000000-0000-4000-8000-000000000001.vtt"]={size:16,body:"Existing fixture"}
    m.top = {cancelled:false}
    outcome = TaskSiloSubtitleFetch(receipt,session,owner)
    agent = invalid
    if m.fixtureAgent <> invalid
        agent = {headers:m.fixtureAgent.headers,cancelled:m.fixtureAgent.cancelled,
                 cert:m.fixtureAgent.cert,peer:m.fixtureAgent.peer,host:m.fixtureAgent.host,
                 url:m.fixtureAgent.url,path:m.fixtureAgent.path}
    end if
    files = []
    for each path in m.fixtureFiles
        files.Push(path)
    end for
    return {outcome:outcome,agent:agent,files:files,downloads:m.fixtureDownloads}
end function
'''


class FetchSdkBoundaryTests(unittest.TestCase):
    def call(self, scenario=None, source=None):
        code = HELPER.read_text()
        for name in ('SiloSubtitleClock', 'SiloSubtitleUuid', 'SiloSubtitleFileSystem',
                     'SiloSubtitleRead', 'SiloSubtitleNewPort', 'SiloSubtitleNewTransfer',
                     'SiloSubtitleWait', 'SiloSubtitleEventType'):
            code = code.replace('function ' + name + '(', 'function Unused' + name + '(', 1)
        with tempfile.TemporaryDirectory(prefix='silo_ui-subtitle-sdk-') as directory:
            source_file = Path(directory) / 'helper.brs'
            boundary = Path(directory) / 'sdk.brs'
            source_file.write_text(code)
            boundary.write_text(SDK_BOUNDARIES)
            return run_function([POLICY, ADAPTER, source_file, boundary],
                                'RunSubtitleSdkFixture', [receipt() if source is None else source,
                                                          SESSION, OWNER, {} if scenario is None else scenario])

    def test_native_empty_stat_for_missing_files_allows_one_owned_artifact(self):
        result=self.call()
        self.assertTrue(result['outcome']['ok'],result)
        self.assertEqual([result['outcome']['uri']],result['files'])
        self.assertEqual(1,len(result['downloads']))
        legacy=self.call({'missingInvalid':True})
        self.assertTrue(legacy['outcome']['ok'],legacy)

    def test_existing_candidate_file_is_never_reused_or_deleted(self):
        result=self.call({'occupied':True})
        self.assertFalse(result['outcome']['ok'],result)
        self.assertEqual('storage_error',result['outcome']['errorCode'])
        self.assertEqual(['tmp:/silo-subtitle-00000000-0000-4000-8000-000000000001.vtt'],result['files'])
        self.assertEqual([],result['downloads'])

    def test_real_helper_fetches_with_bearer_only_and_hands_off_local_file(self):
        result = self.call()
        self.assertTrue(result['outcome']['ok'], result)
        self.assertEqual({'Authorization': 'Bearer fake-access-only'}, result['agent']['headers'])
        self.assertEqual('common:/certs/ca-bundle.crt', result['agent']['cert'])
        self.assertTrue(result['agent']['peer'] and result['agent']['host'])
        self.assertEqual([result['outcome']['uri']], result['files'])
        self.assertNotIn('fake-access-only', str(result['outcome']))
        self.assertNotIn('silo.example', str(result['outcome']))

    def test_real_helper_rejects_bad_status_mime_signature_size_and_cancellation(self):
        cases = (({'status': 302}, 'network_error'),
                 ({'headers': {'Content-Type': 'text/html'}}, 'invalid_subtitle_response'),
                 ({'body': '<html><body>bad</body></html>'}, 'invalid_subtitle_response'),
                 ({'size': 1048577}, 'subtitle_too_large'),
                 ({'cancelOnWait': True}, 'cancelled'),
                 ({'revisionOnWait': True}, 'cancelled'),
                 ({'noEvent': True}, 'network_timeout'),
                 ({'renameOK': False}, 'storage_error'),
                 ({'throwOnWait': True}, 'task_failed'),
                 ({'throwOnRename': True}, 'task_failed'))
        for scenario, error in cases:
            with self.subTest(scenario=scenario):
                result = self.call(scenario)
                self.assertFalse(result['outcome']['ok'], result)
                self.assertEqual(error, result['outcome']['errorCode'])
                self.assertEqual([], result['files'])
                self.assertNotIn('url', str(result['outcome']).lower())
                if 'throwOnWait' in scenario:
                    self.assertTrue(result['agent']['cancelled'])
