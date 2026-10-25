"""Simulated full protocol exchanges; never opens a physical serial port."""
import unittest
from unittest.mock import patch
from mx700_studio.protocol import checksum
from mx700_studio.raw_memory import RawMemoryDocument
from mx700_studio.sync import apply_label_changes, SourceChangedError, ReadbackError


def section():
    data = bytearray(8192)
    data[2] = 0x0a
    data[0x97:0x9c] = b'MAIN '
    data[0x17b5:0x17b5+50] = b' ' * 50
    data[:2] = checksum(data[2:])
    return bytes(data)


def edited(data):
    doc = RawMemoryDocument(data)
    doc.edit_label(doc.devices[0].pages[0].buttons[0], 'TEST')
    return doc.data


class Transport:
    def __init__(self, replies=()):
        self.replies = list(replies)
        self.writes = []
        self.resets = 0
    def write(self, data): self.writes.append(data); return len(data)
    def read(self, count, timeout):
        if not self.replies: return b''
        data = self.replies.pop(0)
        if len(data) > count: self.replies.insert(0, data[count:])
        return data[:count]
    def reset_input_buffer(self): self.resets += 1
    def drain_output(self, timeout): pass


def read_exchange(data): return [b'\xaa', data, checksum(data)]


def exchange(before, desired, after=None):
    return Transport(read_exchange(before) + [b'\xaa', b'\x55', checksum(desired), b'\x55']
                     + read_exchange(desired if after is None else after))


class SyncTests(unittest.TestCase):
    def setUp(self):
        # Remove physical timing only; execute real reader/writer state machines.
        self.patch = patch('mx700_studio.sync.RemoteReader', side_effect=self.reader)
        self.patch2 = patch('mx700_studio.sync.RemoteWriter', side_effect=self.writer)
        self.patch.start(); self.patch2.start()
        self.addCleanup(self.patch.stop); self.addCleanup(self.patch2.stop)
    @staticmethod
    def reader(t):
        from mx700_studio.protocol import RemoteReader
        return RemoteReader(t, sleep=lambda _: None)
    @staticmethod
    def writer(t):
        from mx700_studio.protocol import RemoteWriter
        return RemoteWriter(t, sleep=lambda _: None)
    def test_section_full_exchange(self):
        before = section(); desired = edited(before); t = exchange(before, desired)
        self.assertEqual(apply_label_changes(t, before, desired), desired)
        self.assertEqual(t.writes[:2], [b'\xaa', bytes.fromhex('04 0a 0b 0a 0b')])
        self.assertEqual(t.writes[2:4], [b'\xaa', bytes.fromhex('03 0a 0b 0a 0b')])
        self.assertEqual(b''.join(t.writes[4:10]), desired)
        self.assertEqual(t.writes[10:], [b'\xaa',bytes.fromhex('04 0a 0b 0a 0b')])
    def test_full_image_uses_system_offset_only(self):
        before = bytes(4096) + section() + bytes(0x73000 - 0x3000)
        desired = edited(before)
        t = exchange(before[0x1000:0x3000], desired[0x1000:0x3000])
        self.assertEqual(apply_label_changes(t,before,desired),desired[0x1000:0x3000])
    def test_remote_changed_aborts_before_write_command(self):
        before=section(); desired=edited(before)
        remote=bytearray(before); remote[-1]=1
        t=Transport(read_exchange(bytes(remote)))
        with self.assertRaises(SourceChangedError): apply_label_changes(t,before,desired)
        self.assertEqual(len(t.writes),2)
    def test_readback_mismatch_never_retries(self):
        before=section(); desired=edited(before); t=exchange(before,desired,before)
        with self.assertRaises(ReadbackError): apply_label_changes(t,before,desired)
        self.assertEqual(len(t.writes),12)
        self.assertEqual(t.writes.count(bytes.fromhex('03 0a 0b 0a 0b')),1)
    def assert_rejected_without_io(self,before,desired):
        t=Transport()
        with self.assertRaises((ValueError,TypeError)): apply_label_changes(t,before,desired)
        self.assertEqual(t.writes,[]); self.assertEqual(t.resets,0)
    def test_empty_invalid_mutable_or_different_layout_rejected(self):
        before=section()
        for a,b in [(before,before),(b'',b''),(before,before[:-1]),
                    (bytearray(before),edited(before)),(bytes(8192),bytes(8192))]:
            self.assert_rejected_without_io(a,b)
    def test_nonlabel_changes_rejected(self):
        before=section(); desired=bytearray(edited(before)); desired[-1]=1; desired[:2]=checksum(desired[2:])
        self.assert_rejected_without_io(before,bytes(desired))
        full=bytes(4096)+before+bytes(0x70000)
        modified=bytearray(edited(full));modified[0]=1
        self.assert_rejected_without_io(full,bytes(modified))
    def test_unexposed_and_nonprintable_label_bytes_rejected(self):
        before=section(); desired=bytearray(before); desired[0x815]=65; desired[:2]=checksum(desired[2:])
        self.assert_rejected_without_io(before,bytes(desired))
        desired=bytearray(before);desired[0x17b5]=0; desired[:2]=checksum(desired[2:])
        self.assert_rejected_without_io(before,bytes(desired))
    def test_stale_internal_checksum_rejected_before_io(self):
        before=section(); desired=bytearray(edited(before))
        desired[:2]=before[:2]
        self.assert_rejected_without_io(before,bytes(desired))
    def test_checksum_only_change_rejected_before_io(self):
        before=section(); desired=bytearray(before);desired[0]^=1
        self.assert_rejected_without_io(before,bytes(desired))
