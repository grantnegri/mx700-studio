"""Full replay/preflight/readback tests using actual protocol with fake serial."""
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from mx700_studio.programming import edit, validated_sections, apply_program_changes
from mx700_studio.protocol import RemoteReader, RemoteWriter, full_read_plan, checksum
from mx700_studio.raw_memory import RawMemoryDocument
from mx700_studio.sync import SourceChangedError, ReadbackError
from test_commands import fixture as command_fixture
from test_macros import fixture as macro_fixture
from test_sync import Transport, read_exchange


def fixture():
    data = bytearray(command_fixture())
    data[0x1f000:0x49000] = macro_fixture()[0x1f000:0x49000]
    return bytes(data)


def full_exchange(data):
    replies = []
    for start, end in full_read_plan():
        replies += read_exchange(data[start-0x9000:end+4096-0x9000])
    return replies


def staged(before):
    operations = [('assign_shortcut', (1, 20, 0, 17)),
                  ('copy_learned', (1, 21, 0, 17)),
                  ('set_delay', (0, 5, 1, 10))]
    after = before
    for operation, args in operations:
        after = edit(after, operation, args)
    doc = RawMemoryDocument(after)
    doc.edit_label(doc.devices[0].pages[0].buttons[0], 'TEST')
    return doc.data, operations


class ProgrammingTests(unittest.TestCase):
    def setUp(self):
        self.before = fixture()
        self.after, self.operations = staged(self.before)
        self.patches = [patch('mx700_studio.programming.RemoteReader',
                              side_effect=lambda t: RemoteReader(t, sleep=lambda _: None)),
                        patch('mx700_studio.programming.RemoteWriter',
                              side_effect=lambda t: RemoteWriter(t, sleep=lambda _: None))]
        for p in self.patches:
            p.start(); self.addCleanup(p.stop)

    def test_exact_replay_all_regions_and_shortcuts_last(self):
        sections = validated_sections(self.before, self.after, self.operations)
        self.assertEqual([address for address, _ in sections], [0xA000, 0x28000, 0x54000, 0x9000])
        self.assertEqual([len(data) for _, data in sections], [8192, 8192, 8192, 4096])

    def test_valid_write_exchange_verifies_entire_configuration(self):
        sections = validated_sections(self.before, self.after, self.operations)
        replies = full_exchange(self.before)
        for _, data in sections:
            replies += [b'\xaa', b'\x55', checksum(data), b'\x55']
        replies += full_exchange(self.after)
        t = Transport(replies)
        self.assertEqual(apply_program_changes(t, self.before, self.after, self.operations), self.after)
        self.assertEqual(t.replies, [])
        cursor = 32  # sixteen wakeup/read exchanges before writing
        for address, data in sections:
            first, last = address >> 12, (address+len(data)-4096) >> 12
            self.assertEqual(t.writes[cursor:cursor+2], [b'\xaa', bytes([3, first,last,first,last])])
            chunks = (len(data)+1499)//1500
            self.assertEqual(b''.join(t.writes[cursor+2:cursor+2+chunks]), data)
            cursor += 2+chunks
        self.assertEqual(len(t.writes[cursor:]), 32)  # full readback, not changed ranges only
        for i, (start,end) in enumerate(full_read_plan()):
            self.assertEqual(t.writes[cursor+2*i+1], bytes([4,start>>12,end>>12,start>>12,end>>12]))

    def test_remote_mismatch_stops_before_any_write_command(self):
        remote = bytearray(self.before); remote[-1] ^= 1
        t = Transport(full_exchange(bytes(remote)))
        with self.assertRaises(SourceChangedError):
            apply_program_changes(t, self.before, self.after, self.operations)
        self.assertEqual(len(t.writes), 32)
        self.assertTrue(all(t.writes[i][0] == 4 for i in range(1,32,2)))

    def test_unrelated_mutations_refused_before_serial_io(self):
        for offset in (0x3005, 0x7100, 0x72000):
            bad = bytearray(self.after); bad[offset] ^= 1
            t = Transport()
            with self.subTest(offset=offset):
                with self.assertRaises(ValueError):
                    apply_program_changes(t, self.before, bytes(bad), self.operations)
                self.assertEqual((t.writes, t.resets), ([], 0))
        t = Transport()
        with self.assertRaises(ValueError):
            apply_program_changes(t, self.before, self.after, [])
        self.assertEqual(t.resets, 0)

    def test_no_changes_or_wrong_operations_rejected(self):
        for after, ops in [(self.before, []), (self.after, [('erase', ())]),
                           (self.after, self.operations[:-1])]:
            with self.assertRaises(ValueError): validated_sections(self.before, after, ops)

    def test_full_readback_mismatch_fails_without_retry(self):
        sections = validated_sections(self.before, self.after, self.operations)
        replies = full_exchange(self.before)
        for _, data in sections:
            replies += [b'\xaa', b'\x55', checksum(data), b'\x55']
        wrong = bytearray(self.after); wrong[-1] ^= 1
        t = Transport(replies + full_exchange(bytes(wrong)))
        with self.assertRaises(ReadbackError):
            apply_program_changes(t, self.before, self.after, self.operations)
        self.assertEqual(t.replies, [])
        for address, data in sections:
            first,last=address>>12,(address+len(data)-4096)>>12
            self.assertEqual(t.writes.count(bytes([3,first,last,first,last])),1)

    def test_real_backup_replay_without_hardware(self):
        path = Path(os.environ.get('MX700_RAW_SAMPLE', Path(__file__).resolve().parents[2]/'sr101-original-config.bin'))
        if not path.exists(): self.skipTest('Private hardware backup absent')
        original=path.read_bytes()
        operations=[('set_delay',(0,5,1,10)), ('copy_learned',(20,20,0,20))]
        after=original
        for operation,args in operations: after=edit(after,operation,args)
        sections=validated_sections(original,after,operations)
        self.assertIn(0x28000,[address for address,_ in sections])
        self.assertIn(0x7A000,[address for address,_ in sections])
        self.assertEqual(path.read_bytes(),original)


if __name__=='__main__': unittest.main()
