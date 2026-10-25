"""Pure official48ae/cce Quick Connect auth; all values are synthetic.

No Task wiring, network, storage, device profile or playback owner is introduced.
"""
import copy,json,tempfile,unittest
from pathlib import Path
from tools.brightscript import run_function
ROOT=Path(__file__).resolve().parents[1]
SESSION=dict(baseUrl='https://native.example/app',accessToken='synthetic-native',refreshToken='synthetic-refresh',profileId='profile-current',profileToken='synthetic-pin',deviceId='install-current',model='Current Roku',appVersion='0.2.14',compatToken='a'*32,compatConnectInfo=dict(enabled=True,available=True,publicUrl='https://compat.example:9443/media'))
SECRET='A1'*32
class CompatAuth(unittest.TestCase):
    def call(self,name,*args):
        paths=[ROOT/'source/adapters/SiloAdapter.brs',ROOT/'source/core/ServerUrlPolicy.brs']
        compat=ROOT/'source/adapters/SiloCompatAdapter.brs'
        if name.startswith(('BuildSiloCompat','DecodeSiloCompat')):
            self.assertTrue(compat.is_file(),'pure compatibility adapter missing')
            paths.append(compat)
        with tempfile.TemporaryDirectory() as td:return run_function(paths,name,list(args),root=Path(td))
    def request(self,action,params=None,session=None):return self.call('BuildSiloCompatRequest',action,session or SESSION,params or {})
    def decode(self,action,value,status=200,**params):return self.call('DecodeSiloCompatResponse',action,json.dumps(value),dict(statusCode=status,**params))
    def test_initiate_collect_logout_separate_headers_and_preserve_advertised_prefix(self):
        for action,path,params,body in [('initiate','/QuickConnect/Initiate',{},{}),('collect','/Users/AuthenticateWithQuickConnect',dict(secret=SECRET),dict(Secret=SECRET)),('logout','/Sessions/Logout',{}, {})]:
            with self.subTest(action=action):
                r=self.request(action,params);self.assertTrue(r['ok'],r)
                self.assertEqual(('POST','https://compat.example:9443/media'+path),(r['method'],r['url']))
                self.assertEqual(body,json.loads(r['body']))
                h=r['headers'];self.assertNotIn('X-Profile-Id',h);self.assertNotIn('X-Profile-Token',h)
                self.assertEqual('MediaBrowser Client="Silo Roku", Device="Current Roku", DeviceId="install-current", Version="0.2.14"',h['X-Emby-Authorization'])
                self.assertNotIn('User-Agent',h)
                self.assertNotIn('X-Emby-Token',h)
                if action=='logout':self.assertEqual('Bearer '+'a'*32,h['Authorization'])
                else:self.assertNotIn('Authorization',h)
                self.assertNotIn('synthetic-native',json.dumps(r));self.assertNotIn('synthetic-refresh',json.dumps(r))
    def test_discovery_identity_and_secret_fail_closed(self):
        variants=[dict(compatConnectInfo={}),dict(compatConnectInfo=dict(SESSION['compatConnectInfo'],enabled=False)),dict(compatConnectInfo=dict(SESSION['compatConnectInfo'],publicUrl='https://x.example/media?api_key=x')),dict(compatConnectInfo=dict(SESSION['compatConnectInfo'],publicUrl='http://192.168.1.2/media')),dict(model='bad"identity'),dict(deviceId='bad\r\nInjected:x'),dict(appVersion='')]
        for change in variants:
            with self.subTest(change=change):self.assertFalse(self.request('initiate',session=dict(SESSION,**change))['ok'])
        for value in ('',True,'has space','line\nsecret','A'*1025):
            with self.subTest(secret=value):self.assertFalse(self.request('collect',dict(secret=value))['ok'])
        self.assertFalse(self.request('unsupported')['ok'])
        self.assertFalse(self.request('logout',session=dict(SESSION,compatToken='synthetic-native'))['ok'])
    def test_initiation_private_secret_and_exact_code_no_future_fields(self):
        wire=dict(Authenticated=False,Secret=SECRET,Code='482177',DeviceId='install-current',DeviceName='Current Roku',AppName='Silo Roku',AppVersion='0.2.14',DateAdded='2026-10-17T00:00:00Z')
        r=self.decode('initiate',wire);self.assertTrue(r['ok'],r)
        self.assertEqual(dict(secret=SECRET,code='482177'),r['privateAuth']);self.assertEqual(dict(pending=True),r['data'])
        for change in (dict(Authenticated=True),dict(Code=482177),dict(Code='12345'),dict(Secret='has space'),dict(Authenticated='false')):
            with self.subTest(change=change):self.assertFalse(self.decode('initiate',dict(wire,**change))['ok'])
    def test_collected_token_private_and_logout_strict204(self):
        wire=dict(AccessToken='a'*32,ServerId='server-current',User=dict(Id='00000000-0000-0000-0000-000000000003',Name='Private Name'),SessionInfo=dict(UserId='user-current'))
        r=self.decode('collect',wire);self.assertEqual(dict(compatToken='a'*32,serverId='server-current',compatUserId='00000000-0000-0000-0000-000000000003'),r['privateAuth']);self.assertEqual(dict(authenticated=True),r['data'])
        self.assertNotIn('Private Name',json.dumps(r));self.assertNotIn('user-current',json.dumps(r))
        for value in ('',True,'has space','line\ntoken','a'*4097):
            with self.subTest(value=value):self.assertFalse(self.decode('collect',dict(wire,AccessToken=value))['ok'])
        self.assertEqual(dict(ok=True,data=dict(logoutAcknowledged=True)),self.call('DecodeSiloCompatResponse','logout','',dict(statusCode=204)))
        self.assertFalse(self.decode('logout',{},204)['ok']);self.assertFalse(self.call('DecodeSiloCompatResponse','logout','',dict(statusCode=200))['ok'])
    def test_opaque_secret_and_token_are_not_internal_generator_formats(self):
        secret='opaque_Secret-+/=v2'
        token='opaque_token-+/=v2'
        r=self.request('collect',dict(secret=secret));self.assertTrue(r['ok'],r);self.assertEqual(dict(Secret=secret),json.loads(r['body']))
        r=self.decode('initiate',dict(Authenticated=False,Secret=secret,Code='482177'));self.assertTrue(r['ok'],r)
        r=self.decode('collect',dict(AccessToken=token,ServerId='server-current',User=dict(Id='opaque-user')));self.assertTrue(r['ok'],r);self.assertEqual(dict(compatToken=token,serverId='server-current',compatUserId='opaque-user'),r['privateAuth'])
        self.assertTrue(self.request('logout',session=dict(SESSION,compatToken=token))['ok'])

    def test_collection_requires_actual_authentication_envelope_not_token_only(self):
        for wire in (dict(AccessToken='a'*32),dict(AccessToken='a'*32,ServerId=True,User=dict(Id='00000000-0000-0000-0000-000000000003')),dict(AccessToken='a'*32,ServerId='server-current',User=[])):
            with self.subTest(wire=wire):self.assertFalse(self.decode('collect',wire)['ok'])
        self.assertFalse(self.request('logout',session=dict(SESSION,accessToken='a'*32))['ok'])

    def test_html_wrong_status_nonobject_oversize_refuse_without_echo(self):
        for body,status in [('<html>private</html>',200),('[]',200),('{"AccessToken":"'+'a'*32+'"}',401),('x'*32769,200)]:
            with self.subTest(status=status):
                r=self.call('DecodeSiloCompatResponse','collect',body,dict(statusCode=status));self.assertFalse(r['ok']);self.assertNotIn('private',json.dumps(r))
    def test_native_handoff_uses_only_active_profile_native_headers_and_code(self):
        r=self.call('BuildSiloRequest','compat_handoff_approve',SESSION,dict(code='482177'))
        self.assertTrue(r['ok'],r);self.assertEqual(('POST','https://native.example/app/api/v2/auth/device/approve-handoff'),(r['method'],r['url']))
        self.assertEqual(dict(code='482177'),json.loads(r['body']))
        self.assertEqual('Bearer synthetic-native',r['headers']['Authorization']);self.assertEqual('profile-current',r['headers']['X-Profile-Id']);self.assertEqual('synthetic-pin',r['headers']['X-Profile-Token']);self.assertNotIn('X-Emby-Token',r['headers'])
        for session,params in [(dict(SESSION,profileId=''),dict(code='482177')),(dict(SESSION,accessToken=''),dict(code='482177')),(SESSION,dict(code='12345')),(SESSION,dict(code='482177',profileId='other')),(dict(SESSION,profileToken='x\ny'),dict(code='482177'))]:
            with self.subTest(params=params):self.assertFalse(self.call('BuildSiloRequest','compat_handoff_approve',session,params)['ok'])
    def test_control_characters_never_enter_credential_or_identity_headers(self):
        for control in ('\r','\n','\x7f'):
            for value in ('opaque'+control,control+'opaque','op'+control+'aque'):
                with self.subTest(value=value):
                    self.assertFalse(self.request('collect',dict(secret=value))['ok'])
                    self.assertFalse(self.request('logout',session=dict(SESSION,compatToken=value))['ok'])
                    self.assertFalse(self.call('BuildSiloRequest','compat_handoff_approve',SESSION,dict(code='482177'+control))['ok'])

    def test_native_approval_public_result_strict_status(self):
        r=self.call('DecodeSiloResponse','compat_handoff_approve','{"status":"approved"}',dict(statusCode=200));self.assertEqual(dict(ok=True,data=dict(approved=True)),r)
        for body,status in [('{}',200),('{"status":"pending"}',200),('{"status":"denied"}',200),('{"status":"approved"}',401),('<html/>',200)]:
            with self.subTest(body=body):self.assertFalse(self.call('DecodeSiloResponse','compat_handoff_approve',body,dict(statusCode=status))['ok'])

class NativeHandoffWorker(unittest.TestCase):
    def job(self,*,stale=False,profile_changed=False,job_changes=None,refresh=False,pin_refresh_race=False,status=200,body='{"status":"approved"}'):
        from tests import test_silo_playback_task as playback
        from unittest.mock import patch
        sdk=playback.BOUNDARIES.replace('return m.fixtureSession','return ParseJson(FormatJson(m.fixtureSession))').replace('response = m.responses.Shift()', '''response = m.responses.Shift()
 if m.approvalStale then m.fixtureRevision=m.fixtureRevision+1
 if m.approvalProfileChanged then m.fixtureSession["profileId"]="other-profile"
 if m.pinRefreshRace and Instr(1,request.url,"/auth/refresh")>0 then m.fixtureSession["profileToken"]="synthetic-new-pin"
''')
        sdk+='''
function SaveSession(provider as String,session as Object,expectedRevision as Integer) as Boolean
 if expectedRevision <> m.fixtureRevision then return false
 m.fixtureSession=ParseJson(FormatJson(session))
 return true
end function
function RunNativeHandoff(session as Object,response as Object,stale as Boolean,profileChanged as Boolean,jobChanges as Object,refresh as Boolean,pinRefreshRace as Boolean) as Object
 m.fixtureSession=session:m.fixtureRevision=0:m.requests=[]:m.responses=[response]:m.timeouts=[]:m.changeRevision=false
 m.approvalStale=stale:m.approvalProfileChanged=profileChanged:m.pinRefreshRace=pinRefreshRace
 if refresh
  m.responses=[{statusCode:401,body:"{}"},{statusCode:200,body:"{""access_token"":""synthetic-refreshed"",""refresh_token"":""synthetic-next-refresh"",""expires_in"":3600}"},response]
 end if
 m.top={cancelled:false,job:{provider:"silo",action:"compat_handoff_approve",sourceId:session.sourceId,profileId:session.profileId,generation:4,requestId:9,params:{code:"482177"}}}
 for each key in jobChanges
  if jobChanges[key]=invalid then m.top.job.Delete(key) else m.top.job[key]=jobChanges[key]
 end for
 runJob()
 return {outcome:m.top.result,requests:m.requests,session:m.fixtureSession}
end function
'''
        session=dict(SESSION,sourceId='silo:https://native.example/app');session.pop('compatToken');session.pop('compatConnectInfo')
        with patch.object(playback,'BOUNDARIES',sdk),patch.object(playback,'FILES',playback.FILES+[ROOT/'source/core/ServerUrlPolicy.brs']):
            return playback.SiloPlaybackTaskTests().worker('RunNativeHandoff',[session,dict(statusCode=status,body=body),stale,profile_changed,job_changes or {},refresh,pin_refresh_race])
    def test_actual_run_job_native_approval_public_result_no_session_mutation(self):
        r=self.job();self.assertTrue(r['outcome']['ok'],r['outcome']);self.assertEqual(dict(approved=True),r['outcome']['data'])
        self.assertEqual(1,len(r['requests']));self.assertEqual('profile-current',r['requests'][0]['headers']['X-Profile-Id'])
        self.assertNotIn('synthetic-native',json.dumps(r['outcome']));self.assertNotIn('session',r['outcome'])
        self.assertEqual('profile-current',r['session']['profileId'])
    def test_actual_run_job_does_not_publish_stale_approval(self):
        for change in (dict(stale=True),dict(profile_changed=True)):
            with self.subTest(change=change):
                r=self.job(**change);self.assertFalse(r['outcome']['ok']);self.assertNotIn('data',r['outcome'])

    def test_native_approval_requires_actual_scoped_job_before_http(self):
        for change in (dict(sourceId=None),dict(profileId=None),dict(profileId=''),dict(generation=None),dict(generation=True)):
            with self.subTest(change=change):
                r=self.job(job_changes=change);self.assertFalse(r['outcome']['ok']);self.assertEqual([],r['requests'])

    def test_actual_native_approval_refresh_is_scoped_and_preserves_new_pin(self):
        good=self.job(refresh=True);self.assertTrue(good['outcome']['ok'],good['outcome'])
        self.assertEqual(3,len(good['requests']));self.assertEqual('Bearer synthetic-refreshed',good['requests'][-1]['headers']['Authorization'])
        raced=self.job(refresh=True,pin_refresh_race=True);self.assertFalse(raced['outcome']['ok'],raced['outcome'])
        self.assertEqual(2,len(raced['requests']));self.assertEqual('synthetic-new-pin',raced['session']['profileToken'])
