import tempfile
import unittest
from pathlib import Path

from tools.experiments.owned_compat_setting import OwnedCompatSetting, SettingError, ENDPOINT


class Server:
    def __init__(self):
        self.value = 'http://compat.example:8096'
        self.writes = []
        self.fail_get = False
        self.write_mode = None

    def get(self, path):
        assert path == ENDPOINT
        if self.fail_get:
            raise OSError('unavailable')
        return {'key': 'jellyfin_compat.public_url', 'value': self.value}

    def put(self, path, body):
        assert path == ENDPOINT
        self.writes.append(body['value'])
        if self.write_mode != 'before':
            self.value = body['value']
        if self.write_mode:
            raise OSError('response lost')
        return self.get(path)


class OwnedSettingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'private' / 'setting.json'
        self.server = Server()
        self.setting = self.make()
        self.candidate = 'https://compat.example:8443'

    def make(self, controller='controller-1'):
        return OwnedCompatSetting(self.path, run_id='run-1', server_id='server-1',
                                  controller_id=controller, get=self.server.get, put=self.server.put)

    def test_apply_then_restore_confirms_controller_can_be_revoked(self):
        result = self.setting.prepare(self.candidate)
        self.assertFalse(result['can_revoke_controller'])
        self.assertEqual(self.server.writes, [])
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.setting.apply()['status'], 'applied')
        self.assertTrue(self.setting.restore()['can_revoke_controller'])
        self.assertEqual(self.server.value, 'http://compat.example:8096')

    def test_ambiguous_write_is_observed_once_and_never_blindly_repeated(self):
        for mode, expected in [('after', 'applied')]:
            with self.subTest(mode=mode):
                self.path.unlink(missing_ok=True)
                self.server = Server()
                self.setting = self.make()
                self.setting.prepare(self.candidate)
                self.server.write_mode = mode
                self.assertEqual(self.setting.apply()['status'], expected)
                with self.assertRaises(SettingError):
                    self.setting.apply()
                self.assertEqual(len(self.server.writes), 1)
                self.assertTrue(self.setting.restore()['can_revoke_controller'])

    def test_third_value_and_foreign_receipt_never_write(self):
        self.setting.prepare(self.candidate)
        with self.assertRaises(SettingError):
            self.make('other-controller').restore()
        self.server.value = 'https://other.example'
        for operation in [self.setting.apply, self.setting.restore]:
            with self.assertRaises(SettingError) as caught:
                operation()
            self.assertFalse(caught.exception.can_revoke_controller)
        self.assertEqual(self.server.writes, [])

    def test_get_failure_after_write_keeps_receipt_recoverable(self):
        self.setting.prepare(self.candidate)
        original_put = self.server.put
        def put_then_lose_get(path, body):
            result = original_put(path, body)
            self.server.fail_get = True
            return result
        self.setting.put = put_then_lose_get
        with self.assertRaises(SettingError) as caught:
            self.setting.apply()
        self.assertFalse(caught.exception.can_revoke_controller)
        self.server.fail_get = False
        self.setting = self.make()
        self.assertTrue(self.setting.restore()['can_revoke_controller'])

    def test_failed_restore_retains_controller_and_can_be_recovered(self):
        self.setting.prepare(self.candidate)
        self.setting.apply()
        self.server.write_mode = 'before'
        with self.assertRaises(SettingError) as caught:
            self.setting.restore()
        self.assertFalse(caught.exception.can_revoke_controller)
        self.server.write_mode = None
        with self.assertRaises(SettingError):
            self.make().restore()
        self.assertEqual(len(self.server.writes), 2)
        # The original restore commits late; GET can now prove completion.
        self.server.value = 'http://compat.example:8096'
        self.assertTrue(self.make().restore()['can_revoke_controller'])

    def test_prepare_refusal_proves_no_mutation(self):
        self.server.fail_get = True
        with self.assertRaises(SettingError) as caught:
            self.setting.prepare(self.candidate)
        self.assertTrue(caught.exception.can_revoke_controller)
        self.assertFalse(self.path.exists())
        self.assertEqual(self.server.writes, [])

    def test_rejects_credentials_paths_empty_and_invalid_origins_before_get(self):
        for value in ['', 'https://@compat.example', 'https://user:secret@compat.example',
                      'https://compat.example/', 'https://compat.example?x=1',
                      'https://compat.example:70000', 'file:///tmp/test']:
            with self.subTest(value=value), self.assertRaises(SettingError):
                self.setting.prepare(value)
        self.assertFalse(self.path.exists())

    def test_restore_lost_response_is_confirmed_by_get(self):
        self.setting.prepare(self.candidate)
        self.setting.apply()
        self.server.write_mode = 'after'
        self.assertTrue(self.setting.restore()['can_revoke_controller'])
        self.assertEqual(self.server.writes, [self.candidate, 'http://compat.example:8096'])

    def test_late_apply_commit_cannot_escape_recovery_after_restart(self):
        self.setting.prepare(self.candidate)
        self.server.write_mode = 'before'
        with self.assertRaises(SettingError) as caught:
            self.setting.apply()
        self.assertFalse(caught.exception.can_revoke_controller)
        for _ in range(2):
            with self.assertRaises(SettingError) as caught:
                self.make().restore()
            self.assertFalse(caught.exception.can_revoke_controller)
        self.assertEqual(self.server.writes, [self.candidate])
        # The timed-out original apply commits after the earlier old-value GETs.
        self.server.value = self.candidate
        self.server.write_mode = None
        self.assertTrue(self.make().restore()['can_revoke_controller'])
        self.assertEqual(self.server.writes, [self.candidate, 'http://compat.example:8096'])

    def test_third_value_does_not_erase_pending_apply(self):
        self.setting.prepare(self.candidate)
        self.server.write_mode = 'before'
        with self.assertRaises(SettingError):
            self.setting.apply()
        self.server.value = 'https://other.example'
        with self.assertRaises(SettingError):
            self.make().restore()
        self.server.value = 'http://compat.example:8096'
        with self.assertRaises(SettingError) as caught:
            self.make().restore()
        self.assertFalse(caught.exception.can_revoke_controller)
        self.assertEqual(self.server.writes, [self.candidate])
