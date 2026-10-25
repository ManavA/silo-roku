"""Native account discovery; no compat authentication or playback allocation.

Wire contract: server cce24de2828277bb364c276715e88df9b1f85e8a,
internal/apiv2/operational_discovery.go and internal/jellycompat/connect_info.go.
"""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.brightscript import run_function

ROOT = Path(__file__).resolve().parents[1]
FILES = [ROOT / 'source/adapters/SiloAdapter.brs', ROOT / 'source/core/ServerUrlPolicy.brs']
SESSION = dict(baseUrl='https://native.example', sourceId='silo:https://native.example',
               accessToken='synthetic-native-access', refreshToken='synthetic-native-refresh',
               profileId='fixture-profile', profileToken='synthetic-profile', deviceId='fixture-device')


def advertised(**changes):
    result = dict(jellyfin=dict(enabled=True, pending_restart=False,
                               public_url='https://compat.example:9443/media', server_name='Fixture Silo'),
                  account=dict(password_login_available=True))
    result['jellyfin'].update(changes)
    return result


class SiloCompatDiscoveryAdapterTests(unittest.TestCase):
    def call(self, name, *args):
        with tempfile.TemporaryDirectory() as directory:
            return run_function(FILES, name, list(args), root=Path(directory))

    def decode(self, value, base_url='https://native.example'):
        return self.call('DecodeSiloResponse', 'compat_connect_info', json.dumps(value), dict(baseUrl=base_url))

    def test_native_discovery_is_account_authenticated_get_without_profile_headers(self):
        session = dict(SESSION, profileId='', profileToken='')
        request = self.call('BuildSiloRequest', 'compat_connect_info', session, {})
        self.assertTrue(request['ok'], request)
        self.assertEqual(('GET', 'https://native.example/api/v2/compat/connect-info'),
                         (request['method'], request['url']))
        self.assertEqual('Bearer synthetic-native-access', request['headers']['Authorization'])
        self.assertNotIn('X-Profile-Id', request['headers'])
        self.assertNotIn('X-Profile-Token', request['headers'])
        self.assertEqual('', request['body'])
        scoped = self.call('BuildSiloRequest', 'compat_connect_info', SESSION, {})
        self.assertNotIn('X-Profile-Id', scoped['headers'])
        self.assertNotIn('X-Profile-Token', scoped['headers'])
        denied = self.call('BuildSiloRequest', 'compat_connect_info', dict(session, accessToken=''), {})
        self.assertFalse(denied['ok'])

    def test_discovery_projects_running_listener_and_validated_separate_port_prefix(self):
        result = self.decode(advertised(pending_restart=True, public_url='HTTPS://Compat.Example:9443/media/'))
        self.assertTrue(result['ok'], result)
        self.assertEqual(dict(enabled=True, pendingRestart=True, available=True,
                              publicUrl='https://compat.example:9443/media', serverName='Fixture Silo',
                              passwordLoginAvailable=True), result['data'])
        self.assertNotIn('session', result)

    def test_running_state_and_blank_url_fail_closed_without_inventing_informational_flags(self):
        result = self.decode(advertised(enabled=False, pending_restart=True))
        self.assertTrue(result['ok'])
        self.assertFalse(result['data']['available'])
        self.assertFalse(result['data']['enabled'])
        result = self.decode(advertised(public_url=''))
        self.assertTrue(result['ok'])
        self.assertFalse(result['data']['available'])
        self.assertEqual('', result['data']['publicUrl'])
        old = advertised(); old['jellyfin'].pop('pending_restart'); old.pop('account')
        result = self.decode(old)
        self.assertTrue(result['ok'])
        self.assertFalse(result['data']['pendingRestart'])
        self.assertFalse(result['data']['passwordLoginAvailable'])

    def test_malformed_flags_and_untrusted_advertised_urls_are_never_available(self):
        for field, value in [('enabled', 'true'), ('enabled', 1), ('pending_restart', 'false'),
                             ('public_url', 3), ('server_name', 'bad\nname'), ('server_name', 'x'*257)]:
            with self.subTest(field=field, value=value):
                self.assertFalse(self.decode(advertised(**{field:value}))['ok'])
        for url in ('https://user:secret@compat.example', 'https://compat.example/?token=secret',
                    'https://compat.example/#fragment', '/relative', 'ftp://compat.example',
                    'http://10.0.0.8:8096', 'http://remote.example:8096'):
            with self.subTest(url=url):
                self.assertFalse(self.decode(advertised(public_url=url))['ok'])
        valid = self.decode(advertised(public_url='http://10.0.0.8:8096/prefix'), 'http://10.0.0.9:8080')
        self.assertTrue(valid['ok'])
        malformed = advertised(); malformed['account']['password_login_available'] = 'true'
        self.assertFalse(self.decode(malformed)['ok'])


class SiloCompatDiscoveryWorkerTests(unittest.TestCase):
    def job(self, *, body=None, status=200, params=None, stale=False, source_changed=False):
        from tests import test_silo_playback_task as playback
        value = advertised() if body is None else body
        wrapper = '''
function RunCompatDiscovery(session as Object,response as Object,params as Object,stale as Boolean,sourceChanged as Boolean) as Object
 m.fixtureSession=session:m.fixtureRevision=0:m.requests=[]:m.responses=[response]:m.timeouts=[]:m.changeRevision=false
 m.discoveryStale=stale:m.discoverySourceChanged=sourceChanged
 m.top={cancelled:false,job:{provider:"silo",action:"compat_connect_info",sourceId:session.sourceId,profileId:"",generation:4,requestId:9,params:params}}
 runJob()
 return {outcome:m.top.result,requests:m.requests,session:m.fixtureSession}
end function
'''
        # Registry reads return independent decoded values, not a shared AA.
        sdk = playback.BOUNDARIES.replace('return m.fixtureSession', 'return ParseJson(FormatJson(m.fixtureSession))').replace('response = m.responses.Shift()', '''response = m.responses.Shift()
    if m.discoveryStale=true then m.fixtureRevision=m.fixtureRevision+1
    if m.discoverySourceChanged=true
        changedSession=ParseJson(FormatJson(m.fixtureSession))
        changedSession["sourceId"]="silo:https://changed.example"
        m.fixtureSession=changedSession
    end if''')
        extra = ROOT / 'source/core/ServerUrlPolicy.brs'
        response = dict(statusCode=status, body=json.dumps(value) if not isinstance(value, str) else value)
        with patch.object(playback, 'BOUNDARIES', sdk + wrapper), patch.object(playback, 'FILES', playback.FILES+[extra]):
            return playback.SiloPlaybackTaskTests().worker('RunCompatDiscovery',
                [copy.deepcopy(SESSION), response, params or {}, stale, source_changed])

    def test_actual_worker_discovers_without_profile_or_mutating_session_or_contacting_compat(self):
        result = self.job(params=dict(baseUrl='http://10.0.0.8', publicUrl='http://10.0.0.9'))
        self.assertTrue(result['outcome']['ok'], result['outcome'])
        self.assertEqual('https://compat.example:9443/media', result['outcome']['data']['publicUrl'])
        self.assertEqual(1, len(result['requests']))
        self.assertEqual('https://native.example/api/v2/compat/connect-info', result['requests'][0]['url'])
        self.assertNotIn('X-Profile-Id', result['requests'][0]['headers'])
        self.assertEqual(SESSION, result['session'])
        self.assertNotIn('synthetic-native-access', json.dumps(result['outcome']))

    def test_actual_worker_cannot_override_https_authority_with_request_params(self):
        result = self.job(body=advertised(public_url='http://10.0.0.8:8096'),
                          params=dict(baseUrl='http://10.0.0.9:8080'))
        self.assertFalse(result['outcome']['ok'])
        self.assertNotIn('data', result['outcome'])
        self.assertEqual(1, len(result['requests']))

    def test_actual_worker_discards_discovery_after_session_revision_or_source_changes(self):
        for effect in (dict(stale=True), dict(source_changed=True)):
            with self.subTest(effect=effect):
                result = self.job(**effect)
                self.assertFalse(result['outcome']['ok'], result['outcome'])
                self.assertEqual('session_changed', result['outcome']['errorCode'])
                self.assertNotIn('data', result['outcome'])

    def test_old_server_not_found_and_html_cannot_advertise_a_compat_listener(self):
        for status, body in [(404, '<html>not found</html>'), (200, '<html>proxy login</html>'), (200, {})]:
            with self.subTest(status=status, body=body):
                result = self.job(status=status, body=body)
                self.assertFalse(result['outcome']['ok'], result['outcome'])
                if status == 404:
                    self.assertEqual('not_found', result['outcome']['errorCode'])
                self.assertNotIn('data', result['outcome'])
                self.assertNotIn('plan', result['outcome'])
                self.assertEqual(['GET'], [request['method'] for request in result['requests']])
