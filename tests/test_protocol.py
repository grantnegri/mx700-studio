"""Simulated transport checks against static disassembly; no hardware used."""
import unittest
from mx700_studio.protocol import RemoteReader, ProtocolError, checksum, read_request

class FakeTransport:
    def __init__(self, replies):
        self.replies = list(replies)
        self.writes = []
        self.resets = 0
    def reset_input_buffer(self): self.resets += 1
    def write(self, data):
        self.writes.append(data)
        return len(data)
    def read(self, size, timeout):
        if not self.replies: return b''
        value = self.replies.pop(0)
        if len(value) > size:
            self.replies.insert(0, value[size:])
            value = value[:size]
        return value

class ProtocolTests(unittest.TestCase):
    def test_known_system_section_vector(self):
        # SectionUploadSystemData uses A000..B000, i.e. two blocks.
        self.assertEqual(read_request(0xA000, 0xB000), bytes.fromhex('04 0a 0b 0a 0b'))
        self.assertEqual(checksum(bytes(8192)), bytes.fromhex('0852'))
        self.assertEqual(checksum(bytes(range(256))*32), bytes.fromhex('f852'))
    def test_fragmented_read_and_trailer(self):
        payload = bytes(range(256))*32
        t = FakeTransport([b'\xaa', payload[:17], payload[17:], checksum(payload)])
        self.assertEqual(RemoteReader(t, sleep=lambda _: None).read_blocks(0xA000, 0xB000), payload)
        self.assertEqual(t.writes, [b'\xaa', bytes.fromhex('04 0a 0b 0a 0b')])
    def test_bad_checksum_rejected(self):
        t = FakeTransport([b'\xaa', bytes(4096), b'\0\0'])
        with self.assertRaisesRegex(ProtocolError, 'Checksum'):
            RemoteReader(t, sleep=lambda _: None).read_blocks(0, 0)
    def test_truncated_read_rejected(self):
        t = FakeTransport([b'\xaa', b'abc'])
        with self.assertRaisesRegex(ProtocolError, 'timeout'):
            RemoteReader(t, sleep=lambda _: None).read_blocks(0, 0)
    def test_wakeup_retry_vectors(self):
        for replies in ([b'\xa5',b'\xaa'], [b'\xe1',b'\xaa'], [b'\xeb',b'\xeb'], [b'',b'\xaa']):
            t = FakeTransport(replies)
            RemoteReader(t, sleep=lambda _: None).wakeup()
            self.assertEqual(t.writes, [b'\xaa',b'\xaa'])
    def test_unknown_reply_stops(self):
        t = FakeTransport([b'\x12'])
        with self.assertRaises(ProtocolError): RemoteReader(t, sleep=lambda _: None).wakeup()
        self.assertEqual(t.writes, [b'\xaa'])
    def test_invalid_range_never_touches_port(self):
        for start,end in [(-4096,0),(0,0x100000),(1,4096),(4096,0)]:
            t = FakeTransport([])
            with self.assertRaises(ValueError): RemoteReader(t).read_blocks(start,end)
            self.assertEqual(t.writes, [])
            self.assertEqual(t.resets, 0)



class FullReadPlanTests(unittest.TestCase):
    def test_original_upload_ranges_and_chunk_boundaries(self):
        from mx700_studio.protocol import full_read_plan, CONFIG_SIZE
        expected = ((0x9000,0xF000), (0x10000,0x17000),
                    (0x18000,0x1F000), (0x20000,0x27000),
                    (0x28000,0x2F000), (0x30000,0x37000),
                    (0x38000,0x3F000), (0x40000,0x47000),
                    (0x48000,0x4F000), (0x50000,0x51000),
                    (0x52000,0x59000), (0x5A000,0x61000),
                    (0x62000,0x69000), (0x6A000,0x71000),
                    (0x72000,0x79000), (0x7A000,0x7B000))
        self.assertEqual(full_read_plan(), expected)
        self.assertEqual(sum(last-first+4096 for first,last in expected), CONFIG_SIZE)

class WriteTransport(FakeTransport):
    def __init__(self, replies):
        super().__init__(replies)
        self.events = []
    def write(self, data):
        self.events.append(('write', data))
        return super().write(data)
    def read(self, size, timeout):
        self.events.append(('read', size, timeout))
        return super().read(size, timeout)
    def drain_output(self, timeout):
        self.events.append(('drain', timeout))


class SystemWriteTests(unittest.TestCase):
    def writer(self, transport):
        from mx700_studio.protocol import RemoteWriter
        return RemoteWriter(transport, sleep=lambda _: None)

    def test_exact_original_system_write_exchange(self):
        payload = b'\xf8\x51' + (bytes(range(256)) * 32)[2:]
        t = WriteTransport([b'\xaa', b'\x55', b'\xf9', b'\x9a', b'\x55'])
        self.writer(t).write_system_section(payload)
        self.assertEqual(t.writes[:2], [b'\xaa', bytes.fromhex('03 0a 0b 0a 0b')])
        self.assertEqual([len(p) for p in t.writes[2:]], [1500]*5 + [692])
        self.assertEqual(b''.join(t.writes[2:]), payload)  # no sent checksum
        self.assertEqual(t.resets, 2)
        self.assertEqual(t.events[-4:], [('drain',30.0), ('read',2,4.0),
                                        ('read',1,4.0), ('read',1,5.0)])

    def test_size_and_transport_validation_before_io(self):
        for payload in (b'', bytes(8191), bytes(8193), bytearray(8192)):
            t = WriteTransport([])
            with self.assertRaises(ValueError): self.writer(t).write_system_section(payload)
            self.assertEqual(t.writes, [])
            self.assertEqual(t.resets, 0)
        t = FakeTransport([])
        with self.assertRaises(TypeError): self.writer(t).write_system_section(b'\x08\x52' + bytes(8190))
        self.assertEqual(t.resets, 0)

    def test_internal_checksum_rejected_before_io(self):
        t = WriteTransport([])
        with self.assertRaisesRegex(ValueError, 'internal checksum'):
            self.writer(t).write_system_section(bytes(8192))
        self.assertEqual(t.writes, [])
        self.assertEqual(t.resets, 0)

    def test_ready_failure_never_sends_payload(self):
        for response in (b'',b'\x54'):
            t = WriteTransport([b'\xaa',response])
            with self.assertRaisesRegex(ProtocolError,'ready'):
                self.writer(t).write_system_section(b'\x08\x52' + bytes(8190))
            self.assertEqual(len(t.writes),2)
            self.assertFalse(any(e[0]=='drain' for e in t.events))

    def test_checksum_failure_never_retries_or_claims_completion(self):
        for response in (b'',b'\x08',b'\x08\x53'):
            t = WriteTransport([b'\xaa',b'\x55',response])
            with self.assertRaises(ProtocolError): self.writer(t).write_system_section(b'\x08\x52' + bytes(8190))
            self.assertEqual(len(t.writes),8)
            self.assertEqual(t.resets,1)
            self.assertNotIn(('read',1,5.0),t.events)

    def test_final_ack_is_required(self):
        for response in (b'',b'\x54'):
            t = WriteTransport([b'\xaa',b'\x55',b'\x08\xac',response])
            with self.assertRaisesRegex(ProtocolError,'completion'):
                self.writer(t).write_system_section(b'\x08\x52' + bytes(8190))
            self.assertEqual(t.resets,1)
            self.assertEqual(len(t.writes),8)

    def test_drain_timeout_propagates_without_retry(self):
        class Stalled(WriteTransport):
            def drain_output(self, timeout): raise TimeoutError('drain timeout')
        t = Stalled([b'\xaa',b'\x55'])
        with self.assertRaises(TimeoutError): self.writer(t).write_system_section(b'\x08\x52' + bytes(8190))
        self.assertEqual(len(t.writes),8)
        self.assertEqual(t.resets,1)

if __name__ == '__main__': unittest.main()
