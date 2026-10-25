"""Execute discovery orchestration with socket and monotonic-clock fixtures."""
from pathlib import Path
import tempfile
import unittest
from tools.brightscript import run_function
from tests.test_lan_discovery import POLICY, announcement, TXT

ROOT = Path(__file__).resolve().parents[1]
TASK = ROOT / 'components/LanDiscoveryTask.brs'
BOUNDARY = '''
function LanTaskOpen() as Dynamic
    return {}
end function
function LanTaskSend(socket as Object) as Boolean
    m.sent.Push(m.now)
    return true
end function
function LanTaskReceive(socket as Object) as Dynamic
    if m.events.Count() = 0 then return invalid
    event = m.events.Shift()
    if event.DoesExist("cancel") then m.top.cancelled = true
    if event.DoesExist("generation") then m.top.job = {token:"scan", generation:event.generation}
    if event.DoesExist("late") then m.now = 5000
    return event
end function
function LanTaskElapsed() as Integer
    return m.now
end function
sub LanTaskPause(delay as Integer)
    m.now = m.now + delay
end sub
sub LanTaskClose(socket as Object)
    m.closed = true
end sub
function Fixture(events as Object) as Object
    m.events = events
    m.now = 0
    m.sent = []
    m.closed = false
    m.top = {job:{token:"scan", generation:7}, cancelled:false, result:invalid}
    runLanDiscovery()
    return {result:m.top.result, sent:m.sent, closed:m.closed, elapsed:m.now}
end function
'''

class LanDiscoveryTaskTests(unittest.TestCase):
    def run_scan(self, events=()):
        self.assertTrue(TASK.exists(), 'LAN discovery Task is missing')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = TASK.read_text()
            for name in ('Open', 'Send', 'Receive', 'Elapsed'):
                source = source.replace('function LanTask' + name + '(', 'function UnusedLanTask' + name + '(')
            for name in ('Pause', 'Close'):
                source = source.replace('sub LanTask' + name + '(', 'sub UnusedLanTask' + name + '(')
            task = root / 'Task.brs'
            task.write_text(source)
            fixture = root / 'Fixture.brs'
            fixture.write_text(BOUNDARY)
            return run_function([POLICY, task, fixture], 'Fixture', [list(events)])

    def packet(self, **changes):
        return dict(packet=list(announcement(txt=TXT)), sender='192.168.1.20', port=5353, size=len(announcement(txt=TXT)), **changes)

    def test_finishes_with_three_fixed_queries_and_only_final_candidates(self):
        result = self.run_scan([self.packet()])
        self.assertEqual([0, 1000, 3000], result['sent'])
        self.assertEqual(5000, result['elapsed'])
        self.assertTrue(result['closed'])
        self.assertEqual('complete', result['result']['status'])
        self.assertEqual(('scan', 7), (result['result']['token'], result['result']['generation']))
        self.assertEqual(1, len(result['result']['candidates']))

    def test_task_declares_only_discovery_dependencies(self):
        import xml.etree.ElementTree as ET
        component = ET.parse(ROOT / 'components/LanDiscoveryTask.xml').getroot()
        self.assertEqual('Task', component.get('extends'))
        self.assertEqual({'job', 'result', 'cancelled'},
                         {field.get('id') for field in component.findall('interface/field')})
        self.assertEqual(['pkg:/source/core/LanDiscoveryPolicy.brs',
                          'pkg:/components/LanDiscoveryTask.brs'],
                         [script.get('uri') for script in component.findall('script')])

    def test_cancel_or_generation_change_discards_every_candidate_and_closes(self):
        for event in (self.packet(cancel=True), self.packet(generation=8)):
            with self.subTest(event=event):
                result = self.run_scan([self.packet(), event])
                self.assertIsNone(result['result'])
                self.assertTrue(result['closed'])

    def test_late_receive_is_discarded_and_expired_records_do_not_survive_completion(self):
        result = self.run_scan([self.packet(late=True)])
        self.assertEqual([], result['result']['candidates'])
        expired = self.packet()
        expired['packet'] = list(announcement(txt=TXT, ttl=1))
        self.assertEqual([], self.run_scan([expired])['result']['candidates'])

    def test_receive_cap_oversize_and_wrong_source_port_are_bounded(self):
        oversized = self.packet()
        oversized['size'] = 9001
        wrong_port = self.packet()
        wrong_port['port'] = 1234
        result = self.run_scan([oversized, wrong_port] * 40)
        self.assertEqual(64, result['result']['received'])
        self.assertEqual(32, result['result']['oversized'])
        self.assertEqual([], result['result']['candidates'])
        self.assertTrue(result['closed'])

    def test_receive_error_clears_partial_candidates_and_closes(self):
        result = self.run_scan([self.packet(), {'size': -1}])
        self.assertEqual('unavailable', result['result']['status'])
        self.assertEqual([], result['result']['candidates'])
        self.assertTrue(result['closed'])
