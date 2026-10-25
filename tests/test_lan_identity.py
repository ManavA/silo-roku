"""Selected discovery candidates and anonymous identity consistency policy."""
from pathlib import Path
import unittest
from tools.brightscript import run_function

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / 'source/core/LanIdentityPolicy.brs'
DISCOVERY = ROOT / 'source/core/LanDiscoveryPolicy.brs'
CANDIDATE = dict(instance='silo._silo._tcp.local.', host='silo-fixture.local.',
                 serverId='fixture-id-1', address='192.168.1.20', port=8080, goodbye=False)

class LanIdentityTests(unittest.TestCase):
    def invoke(self, name, *args):
        return run_function([DISCOVERY, POLICY], name, list(args))

    def test_identity_matches_selected_candidate_without_establishing_trust(self):
        result = self.invoke('LanIdentityDecode', CANDIDATE, '{"server_id":"fixture-id-1","name":"Living room"}')
        self.assertEqual(dict(ok=True, serverId='fixture-id-1', trusted=False), result)

    def test_rejects_malformed_wrong_identity_and_large_body(self):
        for body, error in [('{', 'invalid_identity'), ('[]', 'invalid_identity'),
                            ('{"server_id":"other"}', 'identity_mismatch'),
                            ('{"server_id":null}', 'invalid_identity'),
                            (' ' * 16385, 'response_too_large')]:
            with self.subTest(error=error):
                self.assertEqual(dict(ok=False, errorCode=error), self.invoke('LanIdentityDecode', CANDIDATE, body))

    def test_request_requires_selection_from_current_candidate_set_and_literal_private_origin(self):
        result = self.invoke('LanIdentityRequest', [CANDIDATE], 0)
        self.assertEqual(dict(ok=True, address='192.168.1.20', port=8080,
                              serverId='fixture-id-1', path='/api/v2/system/identity'), result)
        for candidates, index in [([], 0), ([CANDIDATE], -1), ([CANDIDATE], 1),
                                  ([dict(CANDIDATE, address='8.8.8.8')], 0),
                                  ([dict(CANDIDATE, address='192.168.1.20/path')], 0),
                                  ([dict(CANDIDATE, port=0)], 0),
                                  ([dict(CANDIDATE, port=8080.5)], 0),
                                  ([dict(CANDIDATE, goodbye=True)], 0),
                                  ([dict(CANDIDATE, serverId='fixture-id-1\n')], 0)]:
            with self.subTest(candidates=candidates, index=index):
                self.assertEqual(dict(ok=False,errorCode='invalid_selection'),
                                 self.invoke('LanIdentityRequest', candidates, index))

    def test_decode_rejects_invalid_selection_before_accessing_identity(self):
        self.assertEqual(dict(ok=False, errorCode='invalid_selection'),
                         self.invoke('LanIdentityDecode', {}, '{"server_id":"fixture-id-1"}'))

    def test_untrusted_json_nesting_is_bounded_before_native_decode(self):
        body = '{"server_id":"fixture-id-1","extra":' + '[' * 17 + '0' + ']' * 17 + '}'
        self.assertEqual(dict(ok=False,errorCode='invalid_identity'), self.invoke('LanIdentityDecode', CANDIDATE, body))
        body = '{"server_id":"fixture-id-1","extra":"[[[\\\"[[["}'
        self.assertTrue(self.invoke('LanIdentityDecode', CANDIDATE, body)['ok'])
