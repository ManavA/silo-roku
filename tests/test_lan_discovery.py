"""Synthetic DNS wire packets execute the pure LAN discovery parser."""
from pathlib import Path
import struct
import unittest
from tools.brightscript import run_function

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / 'source/core/LanDiscoveryPolicy.brs'


def name(value):
    return b''.join(bytes([len(part)]) + part.encode() for part in value.split('.')) + b'\0'


def record(owner, kind, data, ttl=120, cls=0x8001):
    return owner + struct.pack('!HHIH', kind, cls, ttl, len(data)) + data


def announcement(ip=(192, 168, 1, 20), port=8080, txt=b'\x04v=1\x00', ttl=120, label='Silo'):
    # PTR target and SRV/TXT owners use compression into the first record.
    service = name('_silo._tcp.local')
    instance_offset = 12 + len(service) + 10
    instance = bytes([len(label)]) + label.encode() + b'\xc0\x0c'
    owner = struct.pack('!H', 0xc000 | instance_offset)
    host = name('silo-fixture.local')
    records = [record(service, 12, instance, ttl, 1),
               record(owner, 33, struct.pack('!HHH', 0, 0, port) + host, ttl),
               record(owner, 16, txt, ttl), record(host, 1, bytes(ip), ttl)]
    return struct.pack('!6H', 0, 0x8400, 0, len(records), 0, 0) + b''.join(records)


TXT = b'\x03v=1\x0fid=fixture-id-1'


class LanDiscoveryTests(unittest.TestCase):
    def parse(self, packet, sender='192.168.1.20', source_port=5353):
        return run_function(POLICY, 'LanDiscoveryPacket', [list(packet), sender, source_port])

    def test_compressed_service_records_offer_only_literal_sender_and_identity(self):
        result = self.parse(announcement(txt=TXT))
        self.assertEqual([{'instance': 'silo._silo._tcp.local.', 'host': 'silo-fixture.local.', 'serverId': 'fixture-id-1',
                           'address': '192.168.1.20', 'port': 8080, 'goodbye': False}], result)

    def test_invalid_packets_never_offer_a_server(self):
        valid = announcement(txt=TXT)
        cases = [b'', valid[:11], valid[:-1], valid + b'\0', valid + bytes(9001),
                 valid[:2] + b'\x04\x00' + valid[4:],  # query
                 valid[:2] + b'\x8c\x00' + valid[4:],  # opcode
                 valid[:2] + b'\x84\x01' + valid[4:],  # rcode
                 valid[:2] + b'\x86\x00' + valid[4:],  # truncated
                 valid[:6] + b'\x00\x41' + valid[8:],
                 valid[:12] + b'\xc0\x0c' + valid[14:],  # name cycle
                 valid[:12] + b'\xff\xff' + valid[14:],  # pointer outside packet
                 valid[:12] + b'\x40' + valid[13:]]
        for packet in cases:
            with self.subTest(packet=packet[:14]):
                self.assertEqual([], self.parse(packet))

    def test_private_sender_port_and_exact_address_are_required(self):
        for sender in ('8.8.8.8', '127.0.0.1', '169.254.1.1', '192.168.1.21',
                       '192.168.001.20', '192.168.1.20/path', '192.168.1.20:8080'):
            with self.subTest(sender=sender):
                self.assertEqual([], self.parse(announcement(txt=TXT), sender))
        self.assertEqual([], self.parse(announcement(txt=TXT), source_port=1234))
        for ip in ((10, 1, 2, 3), (172, 16, 2, 3), (172, 31, 2, 3)):
            self.assertEqual(1, len(self.parse(announcement(ip=ip, txt=TXT), '.'.join(map(str, ip)))))

    def test_missing_identity_unsupported_txt_and_zero_port_are_rejected(self):
        for txt in (b'', b'\x03v=1', b'\x03v=2\x04id=x',
                    TXT + b'\x03v=1', b'\x03v=1\x0aid=http://x', b'\xffv=1'):
            with self.subTest(txt=txt):
                self.assertEqual([], self.parse(announcement(txt=txt)))
        self.assertEqual([], self.parse(announcement(txt=TXT, port=0)))

    def test_goodbye_ptr_alone_withdraws_only_matching_sender_candidate(self):
        packet = announcement(txt=TXT)
        service = name('_silo._tcp.local')
        bye = struct.pack('!6H', 0, 0x8400, 0, 1, 0, 0) + record(service, 12, name('Silo._silo._tcp.local'), ttl=0, cls=1)
        trace = self.trace([(packet, '192.168.1.20'), (bye, '192.168.1.21'), (bye, '192.168.1.20')])
        self.assertEqual([1, 1, 0], [len(state['candidates']) for state in trace])

    def trace(self, packets):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            wrapper = Path(directory) / 'trace.brs'
            wrapper.write_text('''
function LanTrace(events as Object) as Object
    state = LanDiscoveryCreate()
    trace = []
    for each event in events
        if event.kind = "tick"
            state = LanDiscoveryAdvance(state, event.now)
        else if event.kind = "cancel"
            state = LanDiscoveryCancel(state)
        else
            state = LanDiscoveryReduce(state, event.packet, event.sender, 5353, event.now)
        end if
        trace.Push(state)
    end for
    return trace
end function
''')
            return run_function([POLICY, wrapper], 'LanTrace', [[event if isinstance(event, dict) else {'packet': list(event[0]), 'sender': event[1], 'now': event[2] if len(event) > 2 else 0} for event in packets]])

    def test_record_class_and_exact_correlations_reject_conflicting_or_missing_data(self):
        packet = announcement(txt=TXT)
        # All records IN without the cache flush bit are equally acceptable.
        plain = packet.replace(b'\x80\x01', b'\x00\x01')
        self.assertEqual(1, len(self.parse(plain)))
        bad_class = packet.replace(b'\x80\x01', b'\x80\x03')
        self.assertEqual([], self.parse(bad_class))
        extra = record(name('Silo._silo._tcp.local'), 33, struct.pack('!HHH', 0, 0, 9000) + name('silo-fixture.local'))
        conflict = packet[:6] + b'\x00\x05' + packet[8:] + extra
        self.assertEqual([], self.parse(conflict))
        for kind in (16, 33, 1):
            offset = 12
            # Walk only this fixture's known record lengths, independently of the parser.
            spans = []
            for owner_size in (len(name('_silo._tcp.local')), 2, 2, len(name('silo-fixture.local'))):
                start = offset
                rr_kind, _, _, length = struct.unpack('!HHIH', packet[offset + owner_size:offset + owner_size + 10])
                offset += owner_size + 10 + length
                spans.append((rr_kind, start, offset))
            _, start, end = next(span for span in spans if span[0] == kind)
            missing = packet[:6] + b'\x00\x03' + packet[8:start] + packet[end:]
            self.assertEqual([], self.parse(missing))

    def test_scan_bounds_and_conflicting_identity_remain_rejected(self):
        packet = announcement(txt=TXT)
        conflict = announcement(txt=b'\x03v=1\x0fid=fixture-id-2')
        trace = self.trace([(packet, '192.168.1.20'), (conflict, '192.168.1.20'), (packet, '192.168.1.20')])
        self.assertEqual([1, 0, 0], [len(state['candidates']) for state in trace])
        events = []
        for index in range(18):
            changed = announcement(txt=TXT, label=f'Node{index}')
            events.append((changed, '192.168.1.20'))
        trace = self.trace(events)
        self.assertEqual(16, len(trace[-1]['candidates']))
        trace = self.trace([(packet, '192.168.1.20')] * 66)
        self.assertEqual(64, trace[-1]['packets'])
        self.assertEqual(1, len(trace[-1]['candidates']))

    def test_name_expansion_and_pointer_hops_are_bounded(self):
        packet = announcement(txt=TXT)
        def with_extra(extra):
            return packet[:6] + b'\x00\x05' + packet[8:] + extra
        for hops, expected in ((16, 1), (17, 0)):
            offset = len(packet)
            data_start = offset + 12
            pointers = b''.join(struct.pack('!H', 0xc000 | (data_start + 2 * (index + 1)))
                                for index in range(hops - 1)) + b'\0'
            extra = record(struct.pack('!H', 0xc000 | data_start), 99, pointers, cls=1)
            self.assertEqual(expected, len(self.parse(with_extra(extra))))
        oversized = b''.join(b'\x3f' + b'x' * 63 for _ in range(4)) + b'\0'
        self.assertEqual([], self.parse(with_extra(record(oversized, 99, b'', cls=1))))

    def test_duplicate_txt_keys_are_rejected_even_when_first_value_is_empty(self):
        for prefix in (b'\x02v=', b'\x03id='):
            self.assertEqual([], self.parse(announcement(txt=prefix + TXT)))

    def test_conflict_budget_exhaustion_cannot_reintroduce_an_untracked_conflict(self):
        events = []
        for index in range(17):
            good = announcement(txt=TXT, label=f'Node{index}')
            bad = announcement(txt=b'\x03v=1\x0fid=fixture-id-2', label=f'Node{index}')
            events.extend([(good, '192.168.1.20'), (bad, '192.168.1.20'), (good, '192.168.1.20')])
        trace = self.trace(events)
        self.assertEqual([], trace[-1]['candidates'])
        self.assertLessEqual(len(trace[-1]['conflicts']), 16)


    def test_unknown_txt_fields_are_ignored_without_changing_literal_endpoint(self):
        packet = announcement(txt=TXT + b'\x05url=x' + b'\x07path=/x')
        self.assertEqual(self.parse(announcement(txt=TXT)), self.parse(packet))

    def test_unrelated_host_goodbye_does_not_withdraw_an_address_peer(self):
        packet = announcement(txt=TXT)
        goodbye = struct.pack('!6H', 0, 0x8400, 0, 1, 0, 0) + record(name('unrelated.local'), 1, bytes((192, 168, 1, 20)), ttl=0)
        matching = struct.pack('!6H', 0, 0x8400, 0, 1, 0, 0) + record(name('silo-fixture.local'), 1, bytes((192, 168, 1, 20)), ttl=0)
        trace = self.trace([(packet, '192.168.1.20'), (goodbye, '192.168.1.20'), (matching, '192.168.1.20')])
        self.assertEqual([1, 1, 0], [len(state['candidates']) for state in trace])


    def test_split_records_assemble_in_any_order_without_cross_sender_mixing(self):
        service = name('_silo._tcp.local')
        instance = name('Silo._silo._tcp.local')
        host = name('silo-fixture.local')
        records = [record(service, 12, instance, cls=1),
                   record(instance, 33, struct.pack('!HHH', 0, 0, 8080) + host),
                   record(instance, 16, TXT), record(host, 1, bytes((192, 168, 1, 20)))]
        packets = [struct.pack('!6H', 0, 0x8400, 0, 1, 0, 0) + rr for rr in records]
        for order in ((0, 1, 2, 3), (3, 2, 1, 0)):
            trace = self.trace([(packets[index], '192.168.1.20') for index in order])
            self.assertEqual([0, 0, 0, 1], [len(state['candidates']) for state in trace])
        trace = self.trace([(packets[0], '192.168.1.21')] + [(packet, '192.168.1.20') for packet in packets[1:]])
        self.assertEqual([], trace[-1]['candidates'])

    def test_ttl_expiry_refresh_cancel_and_scan_deadline_use_explicit_clock(self):
        packet = announcement(txt=TXT, ttl=1)
        trace = self.trace([(packet, '192.168.1.20', 0), {'kind': 'tick', 'now': 999},
                            (packet, '192.168.1.20', 999), {'kind': 'tick', 'now': 1000},
                            {'kind': 'tick', 'now': 1999}])
        self.assertEqual([1, 1, 1, 1, 0], [len(state['candidates']) for state in trace])
        trace = self.trace([(announcement(txt=TXT), '192.168.1.20', 0), {'kind': 'cancel'},
                            (announcement(txt=TXT), '192.168.1.20', 1)])
        self.assertEqual([1, 0, 0], [len(state['candidates']) for state in trace])
        self.assertTrue(trace[-1]['closed'])
        self.assertEqual([], trace[-1]['records'])
        trace = self.trace([(packet, '192.168.1.20', 0), {'kind': 'tick', 'now': 5000},
                            (announcement(txt=TXT), '192.168.1.20', 5001)])
        self.assertTrue(trace[-1]['closed'])
        self.assertEqual([], trace[-1]['candidates'])

    def test_uint32_ttl_values_do_not_overflow_or_turn_into_goodbyes(self):
        for ttl, before, after in ((0, 0, 0), (1, 1, 0), (0x7fffffff, 1, 1), (0x80000000, 1, 1), (0xffffffff, 1, 1)):
            with self.subTest(ttl=ttl):
                trace = self.trace([(announcement(txt=TXT, ttl=ttl), '192.168.1.20', 0),
                                    {'kind': 'tick', 'now': 1000}])
                self.assertEqual([before, after], [len(state['candidates']) for state in trace])
                self.assertTrue(all(rr['expires'] <= 6000 for rr in trace[0]['records']))

    def test_cache_and_candidates_stay_bounded_after_many_partial_records(self):
        records = []
        for index in range(64):
            records.append(record(name(f'Node{index}._silo._tcp.local'), 16, TXT))
        packet = struct.pack('!6H', 0, 0x8400, 0, 64, 0, 0) + b''.join(records)
        trace = self.trace([(packet, '192.168.1.20'), (announcement(txt=TXT), '192.168.1.20')])
        self.assertEqual(64, len(trace[-1]['records']))
        self.assertLessEqual(len(trace[-1]['candidates']), 16)
        self.assertEqual([], trace[-1]['candidates'])

    def test_conflict_cannot_hide_behind_the_candidate_projection_limit(self):
        events = [(announcement(txt=TXT, label=f'Node{index}'), '192.168.1.20') for index in range(16)]
        events.append((announcement(txt=TXT, label='Node0', ip=(192, 168, 1, 21)), '192.168.1.21'))
        trace = self.trace(events)
        self.assertEqual(15, len(trace[-1]['candidates']))
        self.assertIn('node0._silo._tcp.local.', trace[-1]['conflicts'])
