"""Recovered section bounds and program/data wrapper differences (no hardware)."""
import unittest
from mx700_studio.protocol import RemoteWriter, ProtocolError, checksum
from test_protocol import WriteTransport, FakeTransport


def payload(size):
    body = bytes((i * 17) % 256 for i in range(size - 2))
    return checksum(body) + body


class SectionWriterTests(unittest.TestCase):
    def test_all_supported_sections_exact_framing_and_wrapper(self):
        for start in [0x9000, 0xA000] + list(range(0x28000, 0x7C000, 0x2000)):
            with self.subTest(start=hex(start)):
                size = 0x1000 if start == 0x9000 else 0x2000
                data = payload(size)
                t = WriteTransport([b'\xaa', b'\x55', checksum(data), b'\x55'])
                RemoteWriter(t, sleep=lambda _: None).write_configuration_section(start, data)
                first, last = start >> 12, (start + size - 4096) >> 12
                self.assertEqual(t.writes[:2], [b'\xaa', bytes([3, first, last, first, last])])
                self.assertEqual(b''.join(t.writes[2:]), data)
                self.assertTrue(all(len(p) <= 1500 for p in t.writes[2:]))
                self.assertEqual(t.events[-1], ('read', 1, 4.0 if start >= 0x28000 else 5.0))
                self.assertEqual(t.resets, 2)

    def test_arbitrary_and_partial_sections_rejected_before_io(self):
        bad = [(0xC000, payload(0x3000)), (0xF000, payload(4096)),
               (0x10000, payload(8192)), (0x7C000, payload(8192)),
               (0x29000, payload(8192)), (0x27000, payload(8192)),
               (0x9000, payload(8192)), (0x28000, payload(4096)),
               (0x28000, payload(0x4000)), (0x28000, bytes(8192)),
               (0x28000, bytearray(payload(8192))), (True, payload(8192)),
               (float(0x9000), payload(4096)), ('0x9000', payload(4096))]
        for start, data in bad:
            t = WriteTransport([])
            with self.subTest(start=start, size=len(data)):
                with self.assertRaises(ValueError):
                    RemoteWriter(t).write_configuration_section(start, data)
                self.assertEqual((t.writes, t.resets), ([], 0))

    def test_missing_drain_rejected_before_io(self):
        t = FakeTransport([])
        with self.assertRaises(TypeError):
            RemoteWriter(t).write_configuration_section(0x9000, payload(4096))
        self.assertEqual(t.resets, 0)

    def test_macro_failures_stop_without_retry(self):
        data = payload(8192)
        for replies, stage in [([b'\xaa', b'\x54'], 'ready'),
                               ([b'\xaa', b'\x55', b'\0\0'], 'checksum'),
                               ([b'\xaa', b'\x55', checksum(data), b'\x54'], 'completion')]:
            t = WriteTransport(replies)
            with self.assertRaisesRegex(ProtocolError, stage):
                RemoteWriter(t, sleep=lambda _: None).write_configuration_section(0x28000, data)
            self.assertEqual(t.writes.count(b'\xaa'), 1)
            self.assertEqual(t.resets, 1)
            if stage == 'ready':
                self.assertEqual(len(t.writes), 2)


if __name__ == '__main__':
    unittest.main()
