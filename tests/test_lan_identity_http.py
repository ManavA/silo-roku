"""Bounded framing of the one anonymous identity endpoint."""
from pathlib import Path
import tempfile
import unittest
from tools.brightscript import run_function
ROOT = Path(__file__).resolve().parents[1]
HTTP = ROOT / 'source/core/LanIdentityHttp.brs'
FIXTURE = '''
function Fixture(packets as Object) as Object
    state = LanIdentityHttpCreate()
    for each packet in packets
        state = LanIdentityHttpFeed(state, packet)
    end for
    result = {done:state.done,errorCode:state.errorCode,size:state.body.Count(),wire:state.wire}
    if state.done and state.errorCode = "" then result.body = state.body.ToAsciiString()
    return result
end function
'''

class IdentityHttpTests(unittest.TestCase):
    def parse(self, wire, split=None):
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / 'fixture.brs'
            fixture.write_text(FIXTURE)
            packets = [list(wire)] if split is None else [list(wire[i:i+split]) for i in range(0,len(wire),split)]
            return run_function([HTTP, fixture], 'Fixture', [packets])

    def test_content_length_success_handles_arbitrary_packet_boundaries(self):
        wire = b'HTTP/1.1 200 OK\r\nContent-Length: 20\r\n\r\n{"server_id":"test"}'
        for split in [None, 1, 7]:
            result = self.parse(wire, split)
            self.assertEqual('', result['errorCode'])
            self.assertTrue(result['done'])
            self.assertEqual('{"server_id":"test"}', result['body'])

    def test_chunked_body_and_trailers_are_decoded_at_byte_boundaries(self):
        wire = b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n7\r\n{"serve\r\nd\r\nr_id":"test"}\r\n0\r\nX-Note: ignored\r\n\r\n'
        result = self.parse(wire, 1)
        self.assertTrue(result['done'])
        self.assertEqual('', result['errorCode'])
        self.assertEqual('{"server_id":"test"}', result['body'])

    def test_ambiguous_encoded_redirect_and_invalid_framing_fail_closed(self):
        cases = [b'HTTP/1.1 302 Found\r\nLocation: http://8.8.8.8/\r\n\r\n',
                 b'HTTP/1.1 401 Unauthorized\r\nContent-Length: 0\r\n\r\n',
                 b'HTTP/1.1 200 OK\r\nContent-Length: 1\r\nTransfer-Encoding: chunked\r\n\r\n',
                 b'HTTP/1.1 200 OK\r\nContent-Length: 1\r\nContent-Length: 1\r\n\r\n',
                 b'HTTP/1.1 200 OK\r\nContent-Length: 1\r\nContent-Encoding: gzip\r\n\r\n',
                 b'HTTP/1.1 200 OK\r\nTransfer-Encoding: gzip, chunked\r\n\r\n',
                 b'HTTP/1.1 200 OK\r\nContent-Length: -1\r\n\r\n',
                 b'HTTP/1.1 200 OK\r\n\r\n',
                 b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\nx\r\n',
                 b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n1\r\naX\r\n']
        for wire in cases:
            with self.subTest(wire=wire[:80]):
                result = self.parse(wire)
                self.assertTrue(result['done'])
                self.assertNotEqual('', result['errorCode'])
                self.assertEqual(0, result['size'])

    def test_header_body_chunk_and_trailer_limits_stop_accumulation(self):
        prefix = b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n'
        cases = [b'HTTP/1.1 200 OK\r\nX: ' + b'a' * 4096,
                 b'HTTP/1.1 200 OK\r\nContent-Length: 16385\r\n\r\n',
                 prefix + b'4001\r\n',
                 prefix + b'0' * 129,
                 prefix + (b'1\r\na\r\n' * 129),
                 prefix + b'0\r\nX: ' + b'a' * 1024]
        for wire in cases:
            with self.subTest(length=len(wire)):
                result = self.parse(wire, 37)
                self.assertTrue(result['done'])
                self.assertNotEqual('', result['errorCode'])
                self.assertEqual(0, result['size'])

    def test_missing_chunk_terminator_fails_immediately_and_exact_body_cap_succeeds(self):
        prefix = b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n'
        result = self.parse(prefix + b'1\r\naX')
        self.assertTrue(result['done'])
        self.assertNotEqual('', result['errorCode'])
        result = self.parse(b'HTTP/1.1 200 OK\r\nContent-Length: 16384\r\n\r\n' + b'a'*16384,1024)
        self.assertTrue(result['done'])
        self.assertEqual('',result['errorCode'])
        self.assertEqual(16384,result['size'])

    def test_embedded_nul_cannot_truncate_body_before_json_validation(self):
        wire = b'HTTP/1.1 200 OK\r\nContent-Length: 3\r\n\r\na\x00b'
        result = self.parse(wire)
        self.assertNotEqual('',result['errorCode'])
        self.assertEqual(0,result['size'])
