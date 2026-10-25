"""Selected identity Task lifecycle at the approved native transport seam."""
from pathlib import Path
import tempfile
import unittest
from tools.brightscript import run_function
from tests.test_lan_identity import CANDIDATE, POLICY, DISCOVERY
from tests.test_lan_identity_http import HTTP
ROOT = Path(__file__).resolve().parents[1]
TASK = ROOT / 'components/LanIdentityTask.brs'
BOUNDARY = '''
function IdentityTaskOpen(request as Object) as Dynamic
    m.opened = true
    return {connected:not m.writablePending,writable:true,healthy:not m.hardError,eOK:FixtureSocketOK,IsConnected:FixtureSocketConnected,IsWritable:FixtureSocketWritable}
end function
function FixtureSocketOK() as Boolean
    return m.healthy
end function
function FixtureSocketConnected() as Boolean
    return m.connected
end function
function FixtureSocketWritable() as Boolean
    return m.writable
end function
function IdentityTaskSend(socket as Object, bytes as Object, offset as Integer) as Integer
    m.sent = m.sent + 1
    m.sendComplete = offset + 1 = bytes.Count()
    if m.peerClosed and m.sendComplete
        socket.connected = false
        socket.writable = false
    end if
    return 1
end function
function IdentityTaskReceive(socket as Object, limit as Integer) as Dynamic
    if m.events.Count() = 0 then return invalid
    event = m.events.Shift()
    if event.DoesExist("cancel") then m.top.cancelled = true
    if event.DoesExist("generation") then m.top.job = {token:"select",generation:event.generation}
    if event.DoesExist("late") then m.now = 5000
    return event
end function
function IdentityTaskElapsed() as Integer
    return m.now
end function
sub IdentityTaskPause(delay as Integer)
    m.now = m.now + delay
end sub
sub IdentityTaskClose(socket as Object)
    m.closed = true
end sub
function Fixture(candidate as Object, events as Object) as Object
    m.now = 0
    m.sendComplete = false
    m.peerClosed = candidate.DoesExist("peerClosed")
    m.writablePending = candidate.DoesExist("writablePending")
    m.hardError = candidate.DoesExist("hardError")
    m.sent = 0
    m.opened = false
    m.closed = false
    m.events = events
    m.top = {job:{token:"select",generation:7,candidates:[candidate],selected:0},cancelled:false,result:invalid}
    runLanIdentity()
    return {result:m.top.result,opened:m.opened,closed:m.closed,sent:m.sent,elapsed:m.now}
end function
'''

class IdentityTaskTests(unittest.TestCase):
    def run_task(self, events=(), candidate=CANDIDATE):
        with tempfile.TemporaryDirectory() as directory:
            task = Path(directory) / 'task.brs'
            source = TASK.read_text()
            for name in ('Open','Send','Receive','Elapsed'):
                source = source.replace('function IdentityTask'+name+'(', 'function NativeIdentityTask'+name+'(')
            for name in ('Pause','Close'):
                source = source.replace('sub IdentityTask'+name+'(', 'sub NativeIdentityTask'+name+'(')
            task.write_text(source)
            fixture = Path(directory) / 'fixture.brs'
            fixture.write_text(BOUNDARY)
            return run_function([DISCOVERY,POLICY,HTTP,task,fixture], 'Fixture',[candidate,list(events)])

    def response(self, body=b'{"server_id":"fixture-id-1"}', **extra):
        wire = b'HTTP/1.1 200 OK\r\nContent-Length: '+str(len(body)).encode()+b'\r\n\r\n'+body
        return dict(packet=list(wire), **extra)

    def test_selected_identity_partial_send_completes_and_closes(self):
        result = self.run_task([self.response()])
        self.assertTrue(result['result']['ok'])
        self.assertEqual(('select',7,False), (result['result']['token'],result['result']['generation'],result['result']['trusted']))
        self.assertGreater(result['sent'],1)
        self.assertTrue(result['closed'])

    def test_writable_pending_connection_sends_and_validates_identity(self):
        result = self.run_task([self.response()], candidate=dict(CANDIDATE,writablePending=True))
        self.assertTrue(result['result']['ok'])
        self.assertEqual('fixture-id-1',result['result']['serverId'])
        self.assertFalse(result['result']['trusted'])
        self.assertGreater(result['sent'],0)
        self.assertTrue(result['closed'])

    def test_socket_error_prevents_send_even_when_writable(self):
        result = self.run_task([self.response()], candidate=dict(CANDIDATE,writablePending=True,hardError=True))
        self.assertEqual('network_error',result['result']['errorCode'])
        self.assertEqual(0,result['sent'])
        self.assertTrue(result['closed'])

    def test_connected_peer_close_still_drains_buffered_identity_response(self):
        result = self.run_task([self.response()], candidate=dict(CANDIDATE,peerClosed=True))
        self.assertTrue(result['result']['ok'])
        self.assertTrue(result['closed'])

    def test_cancel_replacement_and_late_responses_never_publish_success(self):
        for extra in [dict(cancel=True),dict(generation=8),dict(late=True)]:
            with self.subTest(extra=extra):
                result = self.run_task([self.response(**extra)])
                self.assertTrue(result['closed'])
                if 'late' in extra:
                    self.assertEqual('network_timeout',result['result']['errorCode'])
                else:
                    self.assertIsNone(result['result'])

    def test_invalid_origin_never_opens_socket_and_timeout_or_peer_close_cleans_up(self):
        result = self.run_task(candidate=dict(CANDIDATE,address='https://example.com'))
        self.assertFalse(result['opened'])
        self.assertEqual('invalid_selection',result['result']['errorCode'])
        for events, error in [([], 'network_timeout'),([dict(eof=True)],'network_error')]:
            result = self.run_task(events)
            self.assertEqual(error,result['result']['errorCode'])
            self.assertTrue(result['closed'])
            self.assertLessEqual(result['elapsed'],5000)

    def test_wrong_id_and_malformed_json_do_not_validate_selected_source(self):
        for body,error in [(b'{"server_id":"other"}','identity_mismatch'),(b'{','invalid_identity')]:
            result = self.run_task([self.response(body)])
            self.assertEqual(error,result['result']['errorCode'])
            self.assertTrue(result['closed'])
