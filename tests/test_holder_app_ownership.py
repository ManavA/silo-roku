import copy
import hashlib
import unittest

from tools.experiments.holder_app_ownership import OwnershipError, inspect_owned, approve_app_request, revoke_owned_auth, census_with_requests


class HolderAppOwnershipTest(unittest.TestCase):
    def setUp(self):
        self.baselines = dict(auth=[dict(id='old', user_id=7, device_name='old', revoked=True)],
                              requests=[], compat=[], playback=[])
        self.doc = copy.deepcopy(self.baselines)
        self.scope = dict(namespace='holderqa12012', account=7, profile='profile-7', baselines=self.baselines)

    def request(self, purpose, rid, session=None, status='pending', profile=None):
        self.doc['requests'].append(dict(id=rid, device_name='holderqa12012', client_purpose=purpose,
            status=status, approved_by_user_id=7 if status != 'pending' else None,
            approved_profile_id=profile, auth_session_id=session, match_code='ABCD',
            user_code_hash=hashlib.sha256(b'12345678').hexdigest()))
        if session:
            self.doc['auth'].append(dict(id=session, user_id=7, device_name='holderqa12012', revoked=False))

    def test_app_login_and_quick_connect_create_two_linked_auth_rows(self):
        self.request('device_login', 'request-app', 'app', 'consumed')
        self.request('jellyfin_quick_connect', 'request-compat', 'compat-auth', 'consumed', 'profile-7')
        self.doc['compat'].append(dict(token='compat', streamapp_user_id=7, profile_id='profile-7'))
        self.doc['playback'].append(dict(ID='play', CompatToken='compat', ClientDeviceID='holderqa12012'))
        owned = inspect_owned(self.doc, **self.scope)
        self.assertEqual((owned.app_auth_id, owned.compat_auth_id, owned.compat_token, owned.playback_id),
                         ('app', 'compat-auth', 'compat', 'play'))

    def test_pending_app_request_has_no_auth(self):
        self.request('device_login', 'request-app')
        self.assertIsNone(inspect_owned(self.doc, **self.scope).app_auth_id)

    def test_unknown_auth_and_changed_baseline_fail_closed(self):
        self.doc['auth'].append(dict(id='foreign', user_id=7, device_name='holderqa12012', revoked=False))
        with self.assertRaises(OwnershipError):
            inspect_owned(self.doc, **self.scope)
        self.doc['auth'].pop()
        self.doc['auth'][0]['revoked'] = False
        with self.assertRaises(OwnershipError):
            inspect_owned(self.doc, **self.scope)

    def test_quick_connect_must_match_profile_and_session(self):
        self.request('jellyfin_quick_connect', 'request-compat', 'compat-auth', 'consumed', 'other')
        with self.assertRaises(OwnershipError):
            inspect_owned(self.doc, **self.scope)
        self.doc['requests'][0]['approved_profile_id'] = 'profile-7'
        self.doc['requests'][0]['auth_session_id'] = 'missing'
        with self.assertRaises(OwnershipError):
            inspect_owned(self.doc, **self.scope)

    def test_playback_requires_both_token_and_device(self):
        self.request('jellyfin_quick_connect', 'request-compat', 'compat-auth', 'consumed', 'profile-7')
        self.doc['compat'].append(dict(token='compat', streamapp_user_id=7, profile_id='profile-7'))
        self.doc['playback'].append(dict(ID='play', CompatToken='compat', ClientDeviceID='other'))
        with self.assertRaises(OwnershipError):
            inspect_owned(self.doc, **self.scope)

    def test_approval_uses_existing_controller_and_reconciles_observed_request(self):
        self.request('device_login', 'request-app')
        doc = self.doc
        class Gate:
            def validate(self, config, binding, census):
                assert census is doc
            def controller(self, config):
                return {}, {'phase': 'verified'}
        class Driver:
            config = {'user_agent': 'holderqa12012', 'device_id': 'holderqa12012'}
            gate = Gate()
            calls = 0
            def census(self, binding):
                return doc
            def api(self, method, path, body=None, native=False):
                if method == 'GET':
                    assert (path, native) == ('/api/v2/auth/device?code=1234-5678', True)
                    return {'status': 'pending', 'device_name': 'holderqa12012', 'client_purpose': 'device_login', 'match_code': 'ABCD'}
                self.calls += 1
                assert (method, path, body, native) == ('POST', '/api/v2/auth/device/approve', {'code': '1234-5678'}, True)
                doc['requests'][0].update(status='approved', approved_by_user_id=7)
                return {'status': 'approved'}
        driver = Driver()
        binding = {'correlation': {'device_id': 'holderqa12012', 'user_agent': 'holderqa12012'}, 'server': {'account': '7', 'profile': 'profile-7'}}
        owned = approve_app_request(driver, binding, baselines=self.baselines, user_code='1234-5678')
        self.assertEqual(owned.app_request_id, 'request-app')
        self.assertEqual(driver.calls, 1)
        approve_app_request(driver, binding, baselines=self.baselines, user_code='1234-5678')
        self.assertEqual(driver.calls, 1)

    def test_revoke_uses_exact_owned_id_and_verifies_census(self):
        self.request('device_login', 'request-app', 'app', 'consumed')
        doc = self.doc
        class Gate:
            def validate(self, config, binding, census):
                assert census is doc
            def controller(self, config):
                return {}, {'phase': 'verified'}
        class Driver:
            config = {'user_agent': 'holderqa12012', 'device_id': 'holderqa12012'}
            gate = Gate()
            calls = 0
            def census(self, binding):
                return doc
            def api(self, method, path, want, native):
                self.calls += 1
                assert (method, path, want, native) == ('DELETE', '/api/v2/auth/sessions/app', 204, True)
                doc['auth'][-1]['revoked'] = True
        driver = Driver()
        binding = {'correlation': {'device_id': 'holderqa12012', 'user_agent': 'holderqa12012'}, 'server': {'account': '7', 'profile': 'profile-7'}}
        with self.assertRaises(OwnershipError):
            revoke_owned_auth(driver, binding, baselines=self.baselines, auth_id='old')
        revoke_owned_auth(driver, binding, baselines=self.baselines, auth_id='app')
        revoke_owned_auth(driver, binding, baselines=self.baselines, auth_id='app')
        self.assertEqual(driver.calls, 1)

    def test_foreign_lookup_code_never_posts_approval(self):
        self.request('device_login', 'request-app')
        doc = self.doc
        class Gate:
            def validate(self, *args):
                pass
            def controller(self, config):
                return {}, {'phase': 'verified'}
        class Driver:
            config = {'user_agent': 'holderqa12012', 'device_id': 'holderqa12012'}
            gate = Gate()
            def census(self, binding):
                return doc
            def api(self, method, path, body=None, native=False):
                if method != 'GET':
                    raise AssertionError('foreign code approved')
                return {'status': 'pending', 'device_name': 'foreign',
                        'client_purpose': 'device_login', 'match_code': 'ABCD'}
        binding = {'correlation': {'device_id': 'holderqa12012', 'user_agent': 'holderqa12012'}, 'server': {'account': '7', 'profile': 'profile-7'}}
        with self.assertRaises(OwnershipError):
            approve_app_request(Driver(), binding, baselines=self.baselines, user_code='1234-5678')
        with self.assertRaises(OwnershipError):
            approve_app_request(Driver(), binding, baselines=self.baselines, user_code='9999-9999')

    def test_request_census_retries_consumption_between_auth_and_request_reads(self):
        import json
        self.request('device_login', 'request-app', 'app', 'consumed')
        complete = copy.deepcopy(self.doc)
        before = copy.deepcopy(complete)
        before['auth'] = copy.deepcopy(self.baselines['auth'])
        for doc in (before, complete):
            doc.pop('requests')
        class IO:
            def command(inner, *args, **kwargs):
                return json.dumps({'installation': 'server-1', 'count': 1,
                                   'rows': self.doc['requests']}).encode()
        class Driver:
            io = IO()
            server = {'names': {'pg': 'owned-pg'}}
            reads = 0
            def census(inner, binding):
                inner.reads += 1
                return before if inner.reads == 1 else complete
            def left(inner):
                return 3
        driver = Driver()
        doc = census_with_requests(driver, {'server': {'identity': 'server-1'}})
        self.assertEqual(inspect_owned(doc, **self.scope).app_auth_id, 'app')
        self.assertLessEqual(driver.reads, 6)

    def test_request_census_accepts_playback_progress_during_stable_auth_reads(self):
        import json
        class IO:
            def command(inner, *args, **kwargs):
                return json.dumps({'installation': 'server-1', 'count': 0, 'rows': []}).encode()
        class Driver:
            io = IO()
            server = {'names': {'pg': 'owned-pg'}}
            reads = 0
            def census(inner, binding):
                inner.reads += 1
                return {'auth': [], 'compat': [],
                        'playback': [{'ID': 'play', 'PositionTicks': inner.reads}]}
            def left(inner):
                return 3
        driver = Driver()
        doc = census_with_requests(driver, {'server': {'identity': 'server-1'}})
        self.assertEqual(doc['playback'][0]['PositionTicks'], 1)
        self.assertEqual(driver.reads, 2)

    def test_request_census_fails_closed_when_identity_rows_keep_changing(self):
        import json
        class IO:
            def command(inner, *args, **kwargs):
                return json.dumps({'installation': 'server-1', 'count': 0, 'rows': []}).encode()
        class Driver:
            io = IO()
            server = {'names': {'pg': 'owned-pg'}}
            reads = 0
            def census(inner, binding):
                inner.reads += 1
                return {'auth': [{'id': str(inner.reads)}], 'compat': [], 'playback': []}
            def left(inner):
                return 3
        driver = Driver()
        with self.assertRaisesRegex(OwnershipError, 'request census did not stabilize'):
            census_with_requests(driver, {'server': {'identity': 'server-1'}})
        self.assertEqual(driver.reads, 6)

    def test_request_census_checks_installation_and_complete_count(self):
        import json
        class IO:
            answer = {'installation': 'server-1', 'count': 1, 'rows': []}
            def command(self, args, remaining, data, limit):
                self.sql = data.decode()
                assert remaining == 3 and 'BEGIN READ ONLY' in self.sql
                assert 'device_login_requests' in self.sql
                return json.dumps(self.answer).encode()
        class Driver:
            io = IO()
            server = {'names': {'pg': 'owned-pg'}}
            def census(self, binding):
                return {'auth': [], 'compat': [], 'playback': []}
            def left(self):
                return 3
        driver = Driver()
        with self.assertRaises(OwnershipError):
            census_with_requests(driver, {'server': {'identity': 'server-1'}})
        driver.io.answer = {'installation': 'foreign', 'count': 0, 'rows': []}
        with self.assertRaises(OwnershipError):
            census_with_requests(driver, {'server': {'identity': 'server-1'}})

    def test_mismatched_run_identity_blocks_approval_and_revocation_before_io(self):
        class Driver:
            config = {'user_agent': 'other', 'device_id': 'holderqa12012'}
            def census(self, binding):
                raise AssertionError('identity mismatch reached IO')
            def api(self, *args, **kwargs):
                raise AssertionError('identity mismatch mutated server')
        binding = {'correlation': {'device_id': 'holderqa12012', 'user_agent': 'holderqa12012'},
                   'server': {'account': '7', 'profile': 'profile-7'}}
        with self.assertRaises(OwnershipError):
            approve_app_request(Driver(), binding, baselines=self.baselines, user_code='1234-5678')
        with self.assertRaises(OwnershipError):
            revoke_owned_auth(Driver(), binding, baselines=self.baselines, auth_id='app')


if __name__ == '__main__':
    unittest.main()
