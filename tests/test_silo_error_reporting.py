"""Bounded playback error events use the real worker and one HTTP attempt."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

from tools.brightscript import run_function

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
import test_silo_playback_task as playback

SILO = ROOT / 'source/adapters/SiloAdapter.brs'
EVENT_ID = '10000000-0000-4000-8000-000000000001'
SESSION = {'baseUrl':'https://silo.example','sourceId':'silo:synthetic','profileId':'owner',
           'deviceId':'device-1','accessToken':'synthetic-access','profileToken':'synthetic-profile'}
PARAMS = {'report':{'installationId':'install-1','playbackAttemptId':'attempt-12345678'},
          'supportCode':'2005','errorCode':'playback_terminal','reason':'audio_conversion_unsupported'}
BOUNDARY = '''
function TaskDeviceSession(provider as String, session as Object) as Object
 return session
end function
function RunReport(params as Object, scope as Object, status as Integer, changed as Boolean) as Object
 m.requests=[]:m.timeouts=[]:m.fixtureRevision=0:m.changeRevision=false:m.fixtureSession=ParseJson("SESSION_JSON")
 if changed then m.fixtureRevision=1
 m.responses=[{statusCode:status,body:FormatJson({event_id:"10000000-0000-4000-8000-000000000001",outcome:"accepted",private:"private-token"})}]
 result=ExecuteApiAction("silo","playback_error_report",params,scope)
 return {outcome:result,requests:m.requests,timeouts:m.timeouts}
end function
'''.replace('SESSION_JSON',json.dumps(SESSION).replace('"','""'))


class SiloErrorReportingTests(unittest.TestCase):
    def test_report_includes_only_a_bounded_device_model_from_session(self):
        params=copy.deepcopy(PARAMS);params['eventId']=EVENT_ID
        value=run_function(SILO,'BuildSiloRequest',['playback_error_report',{**SESSION,'model':'4850X'},params])
        self.assertEqual('4850X',json.loads(value['body'])['diagnostics'].get('device_model'))
        value=run_function(SILO,'BuildSiloRequest',['playback_error_report',{**SESSION,'model':'private device https://private.example'},params])
        self.assertNotIn('device_model',json.loads(value['body'])['diagnostics'])

    def request(self, params=None):
        params = copy.deepcopy(PARAMS if params is None else params)
        params['eventId'] = EVENT_ID
        return run_function(SILO,'BuildSiloRequest',['playback_error_report',SESSION,params])

    def dispatch(self, params=None, status=202, changed=False, scope=None):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            task=root/'ApiTask.brs'
            task.write_text((ROOT/'components/ApiTask.brs').read_text().replace('function TaskDeviceSession(','function UnusedTaskDeviceSession(',1).replace('function TaskUniqueId(','function UnusedTaskUniqueId(',1).replace('function TaskRokuSiloContext(','function UnusedTaskRokuSiloContext(',1).replace('CreateObject("roDeviceInfo")','FixtureSiloDevice()'))
            http=root/'Http.brs';http.write_text((ROOT/'source/network/Http.brs').read_text().replace('function HttpRequest(','function UnusedHttpRequest(',1))
            boundary=root/'boundaries.brs';boundary.write_text(playback.BOUNDARIES+BOUNDARY)
            return run_function([*playback.FILES,task,http,boundary],'RunReport',[
                PARAMS if params is None else params,
                {'sourceId':'silo:synthetic','profileId':'owner','sessionRevision':0} if scope is None else scope,
                status,changed],root=root)

    def test_builder_sends_string_diagnostics_with_no_raw_failure_fields(self):
        value=self.request();self.assertTrue(value['ok'],value)
        self.assertEqual('POST',value['method'])
        self.assertEqual('https://silo.example/api/v2/playback/route-events',value['url'])
        body=json.loads(value['body'])
        self.assertEqual('terminal',body['event'])
        self.assertNotIn('session_id',body)
        self.assertEqual({'error_code':'2005','error_code_name':'playback_terminal','reason':'audio_conversion_unsupported'},body['diagnostics'])
        self.assertEqual(EVENT_ID,body['event_id'])
        params=copy.deepcopy(PARAMS);params['report']['sessionId']='session-1'
        self.assertEqual('plan_failed',json.loads(self.request(params)['body'])['event'])

    def test_builder_refuses_unexpected_fields_and_private_id_or_code(self):
        for change in ({'message':'private-token'},{'supportCode':'private-token'},{'supportCode':'9999'}):
            params=copy.deepcopy(PARAMS);params.update(change)
            self.assertFalse(self.request(params)['ok'])
        for key,value in [('installationId','https://private.example/token'),('playbackAttemptId','short'),('private','private-token')]:
            params=copy.deepcopy(PARAMS);params['report'][key]=value
            self.assertFalse(self.request(params)['ok'])

    def test_recovery_job_timeout_uses_existing_allowlisted_diagnostic(self):
        params=copy.deepcopy(PARAMS)
        params.update(supportCode='3002',errorCode='network_timeout',reason='')
        result=self.request(params)
        self.assertTrue(result['ok'],result)
        self.assertEqual({'error_code':'3002','error_code_name':'network_timeout'},json.loads(result['body'])['diagnostics'])

    def test_unknown_reason_and_code_never_enter_diagnostics(self):
        params=copy.deepcopy(PARAMS);params.update(errorCode='private-token',reason='https://private.example')
        result=self.request(params)
        self.assertTrue(result['ok'])
        self.assertNotIn('private',result['body'])
        self.assertEqual({'error_code':'2005'},json.loads(result['body'])['diagnostics'])

    def test_native_error_name_accepts_only_generated_numeric_shape(self):
        params=copy.deepcopy(PARAMS);params.update(supportCode='3001',errorCode='roku_native_-5')
        self.assertEqual('roku_native_-5',json.loads(self.request(params)['body'])['diagnostics'].get('error_code_name'))
        params['errorCode']='roku_native_private-token'
        self.assertNotIn('error_code_name',json.loads(self.request(params)['body'])['diagnostics'])

    def test_receipt_decoder_checks_identity_and_drops_untrusted_properties(self):
        receipt=json.dumps({'event_id':EVENT_ID,'outcome':'accepted','detail':'private-token'})
        result=run_function(SILO,'DecodeSiloResponse',['playback_error_report',receipt,{'eventId':EVENT_ID}])
        self.assertEqual({'ok':True,'data':{'reported':True}},result)
        result=run_function(SILO,'DecodeSiloResponse',['playback_error_report',receipt,{'eventId':'different'}])
        self.assertFalse(result['ok'])

    def test_actual_dispatch_sends_once_with_three_second_budget_and_no_refresh(self):
        for status in (202,401,404,429,503):
            with self.subTest(status=status):
                value=self.dispatch(status=status)
                self.assertEqual(1,len(value['requests']),value)
                self.assertEqual([3000],value['timeouts'])
                self.assertEqual({'ok':True,'data':{'reported':status==202}},value['outcome'])
                self.assertNotIn('private-token',json.dumps(value['outcome']))

    def test_actual_dispatch_rejects_old_scope_before_sending(self):
        value=self.dispatch(changed=True)
        self.assertEqual([],value['requests'])
        self.assertEqual('session_changed',value['outcome']['errorCode'])
        value=self.dispatch(scope={'sourceId':'silo:synthetic','profileId':'other','sessionRevision':0})
        self.assertEqual([],value['requests'])
        self.assertEqual('session_changed',value['outcome']['errorCode'])


if __name__=='__main__':
    unittest.main()
