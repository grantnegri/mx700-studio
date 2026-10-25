import tempfile
import unittest
from pathlib import Path
from mx700_studio.raw_memory import RawMemoryDocument, section_checksum
from mx700_studio.mxf import MxfFormatError


def fixture(full=False):
    section = bytearray(8192)
    section[:3] = bytes.fromhex('8f910a')
    section[0x97:0x9c] = b'MAIN '
    section[0x815:0x1819] = b' ' * (0x1819 - 0x815)
    section[3:5] = (0x200).to_bytes(2, 'little')
    section[0x800] = 1
    section[0x814] = 1
    section[0x17ba:0x17bf] = b' HDMI'
    section[0x815:0x81a] = b'CCAST'
    section[0x81a:0x81f] = b'   PC'
    section[:2] = section_checksum(section).to_bytes(2, 'big')
    if not full:
        return bytes(section)
    data = bytearray(b'\xa5' * 0x73000)
    data[0x1000:0x3000] = section
    return bytes(data)


class RawMemoryTests(unittest.TestCase):
    def test_parse_and_exact_identity(self):
        for full in (False, True):
            data = fixture(full)
            document = RawMemoryDocument(data)
            self.assertEqual(document.data, data)
            self.assertEqual([d.name for d in document.devices], ['MAIN', 'HDMI'])
            self.assertFalse(document.dirty)

    def test_staging_reparse_and_untouched_other_bytes(self):
        for full in (False, True):
            data = fixture(full)
            document = RawMemoryDocument(data)
            buttons = document.devices[1].pages[0].buttons
            document.edit_label(buttons[0], 'CAST')
            document.edit_label(buttons[1], 'LINUX')
            allowed = set(range(buttons[0].offset, buttons[1].offset + 5)) | {document.section_file_offset, document.section_file_offset + 1}
            self.assertTrue(all(a == b for i, (a, b) in enumerate(zip(data, document.data)) if i not in allowed))
            self.assertEqual(len(data), len(document.data))
            self.assertTrue(document.dirty)
            self.assertEqual(RawMemoryDocument(document.data).devices[1].pages[0].buttons[1].label, 'LINUX')
            if full:
                self.assertEqual(document.data[:0x1000], data[:0x1000])
                self.assertEqual(document.data[0x3000:], data[0x3000:])

    def test_alignment_blank_label_and_name_update(self):
        document = RawMemoryDocument(fixture())
        right = document.devices[1].pages[0].buttons[1]
        document.edit_label(right, 'TV')
        self.assertEqual(document.data[right.offset:right.offset+5], b'   TV')
        document.edit_label(right, '')
        self.assertEqual(document.data[right.offset:right.offset+5], b'     ')
        self.assertEqual(RawMemoryDocument(document.data).devices[1].pages[0].buttons[1].label, '')
        main_right = document.devices[0].pages[0].buttons[1]
        document.edit_label(main_right, 'INPUT')
        self.assertEqual(document.devices[1].name, 'INPUT')
        self.assertEqual(RawMemoryDocument(document.data).devices[1].name, 'INPUT')

    def test_limits_and_foreign_button(self):
        document = RawMemoryDocument(fixture())
        button = document.devices[1].pages[0].buttons[0]
        for text in ('TOOLONG', 'é', '\n'):
            with self.assertRaises(ValueError): document.edit_label(button, text)
        other = RawMemoryDocument(fixture()).devices[1].pages[0].buttons[0]
        with self.assertRaises(ValueError): document.edit_label(other, 'ABC')
        self.assertEqual(document.data, fixture())

    def test_save_copy_preserves_source(self):
        with tempfile.TemporaryDirectory() as folder:
            source, target = Path(folder)/'original.bin', Path(folder)/'copy.bin'
            source.write_bytes(fixture(True))
            document = RawMemoryDocument.load(source)
            document.edit_label(document.devices[1].pages[0].buttons[0], 'CAST')
            with self.assertRaises(ValueError): document.save(source)
            document.save(target)
            self.assertEqual(source.read_bytes(), fixture(True))
            self.assertEqual(target.read_bytes(), document.data)
            self.assertFalse(document.dirty)
            with self.assertRaises(FileExistsError): document.save(target)

    def test_checksum_and_unknown_header_preservation(self):
        data = bytearray(fixture())
        data[2] = 0x12
        data[:2] = section_checksum(data).to_bytes(2, 'big')
        document = RawMemoryDocument(data)
        document.edit_label(document.devices[1].pages[0].buttons[0], 'ABC')
        self.assertEqual(document.data[2], 0x12)
        self.assertEqual(int.from_bytes(document.data[:2], 'big'), section_checksum(document.data))
        damaged = bytearray(document.data)
        damaged[0x815] ^= 1
        with self.assertRaises(MxfFormatError): RawMemoryDocument(damaged)

    def test_invalid_layout(self):
        for data in (b'', bytes(8192), bytes(471040)):
            with self.assertRaises(MxfFormatError): RawMemoryDocument(data)

    def test_actual_backup_if_present(self):
        source = Path(__file__).resolve().parents[2]/'sr101-original-config.bin'
        if not source.exists(): self.skipTest('Private hardware backup is not bundled with application')
        before = source.read_bytes()
        document = RawMemoryDocument.load(source)
        self.assertEqual([(d.name, len(d.pages)) for d in document.devices],
                         [('MAIN',1), ('HDMI',2), ('KAICO',1), ('B&K',3), ('BENQ',1)])
        button = document.devices[1].pages[0].buttons[0]
        document.edit_label(button, 'CAST')
        self.assertEqual(RawMemoryDocument(document.data).devices[1].pages[0].buttons[0].label, 'CAST')
        self.assertEqual(document.data[:0x1000], before[:0x1000])
        self.assertEqual(document.data[0x3000:], before[0x3000:])
        self.assertTrue(all(a==b for i,(a,b) in enumerate(zip(before,document.data)) if not (button.offset<=i<button.offset+5 or 0x1000<=i<0x1002)))
        self.assertEqual(source.read_bytes(), before)

if __name__ == '__main__':
    unittest.main()
