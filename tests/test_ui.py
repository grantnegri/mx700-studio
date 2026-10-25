"""Run with QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests.

Optional MX700_LEGACY_SAMPLE and MX700_MODERN_SAMPLE paths run these same native
controls against real files instead of the small generated format fixtures.
"""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QMessageBox
from mx700_studio.mxf import MxfDocument
from mx700_studio.ui import MainWindow, ReadWorker, WriteWorker, STYLE


def seal_system(data):
    data[:2] = ((0x0852 + sum(data[2:])) & 0xffff).to_bytes(2, 'big')
    return data


def record(text, identifier, kind=7):
    raw = text.encode('ascii')
    return bytes([0x16, 0, kind, 0]) + identifier.to_bytes(2, 'little') + len(raw).to_bytes(2, 'little') + bytes(4) + raw + b'\0'


def fixture(modern=False):
    if modern:
        return (bytes.fromhex('210025007000') + b'\xff' + record('Page 1', 1, 0x70)
                + record('PLAY', 2, 0x70) + b'\xff' + record('MAIN', 0x8002, 0x70)
                + record('MAIN', 0x8001, 0x70))
    return (b'fixture' + record('MAIN', 0x8002) + record('MAIN', 0x8001)
            + record('Page 1', 1) + record('PLAY', 2) + record('Play', 3))


class NativeUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle('Fusion')
        cls.app.setStyleSheet(STYLE)

    def exercise(self, modern):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / ('template.dat' if modern else 'sample.mxf')
            external = os.environ.get('MX700_MODERN_SAMPLE' if modern else 'MX700_LEGACY_SAMPLE')
            source.write_bytes(Path(external).read_bytes() if external else fixture(modern))
            original = source.read_bytes()
            window = MainWindow(source)
            window.show()
            self.app.processEvents()
            self.assertGreater(window.tree.topLevelItemCount(), 0)
            self.assertEqual(window.preview.isVisible(), not modern)
            expected_column = 'TEXT RECORD' if modern else 'BUTTON LABEL'
            self.assertEqual(window.table.horizontalHeaderItem(0).text(), expected_column)
            # Real templates may begin with an empty record. Pick editable text.
            row = next(i for i, button in enumerate(window.page.buttons) if button.max_length)
            window.table.selectRow(row)
            text = 'X' if window.button.label != 'X' else 'Y'
            window.label_edit.setText(text)
            self.assertTrue(window.apply_button.isEnabled())
            offset = window.button.offset
            window.apply_label()
            self.assertTrue(window.document.dirty)
            with patch('mx700_studio.ui.QMessageBox.question', return_value=QMessageBox.Cancel):
                self.assertFalse(window.confirm_discard())
            with patch('mx700_studio.ui.QFileDialog.getSaveFileName', return_value=(str(source), '')):
                with patch('mx700_studio.ui.QMessageBox.warning'):
                    self.assertFalse(window.save_copy())
            self.assertEqual(source.read_bytes(), original)
            target = Path(temp) / 'edited.mxf'
            with patch('mx700_studio.ui.QFileDialog.getSaveFileName', return_value=(str(target), '')):
                self.assertTrue(window.save_copy())
            self.assertFalse(window.document.dirty)
            parsed = MxfDocument.load(target)
            saved = next(button for device in parsed.devices for page in device.pages for button in page.buttons if button.offset == offset)
            self.assertEqual(saved.label, text)
            self.assertEqual(source.read_bytes(), original)
            self.assertTrue(window.confirm_discard())
            window.close()

    def test_legacy_edit_and_safe_copy(self):
        self.exercise(False)

    def test_modern_text_records_and_safe_copy(self):
        self.exercise(True)

    def test_raw_memory_stages_local_copy(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'remote.bin'
            external = os.environ.get('MX700_RAW_SAMPLE')
            if external:
                source.write_bytes(Path(external).read_bytes())
            else:
                data = bytearray(8192)
                data[2] = 0x0a
                data[0x97:0x9c] = b'MAIN '
                data[0x17b5:0x17b5 + 50] = b' ' * 50
                data[0x17b5:0x17ba] = b'TV   '
                source.write_bytes(seal_system(data))
            original = source.read_bytes()
            window = MainWindow(source)
            window.show()
            self.app.processEvents()
            self.assertTrue(window.preview.isVisible())
            self.assertTrue(window.label_edit.isEnabled())
            self.assertFalse(window.apply_button.isEnabled())
            self.assertTrue(window.save_button.isEnabled())
            window.label_edit.setText('TEST')
            window.apply_label()
            self.assertTrue(window.document.dirty)
            target = Path(temp) / 'edited.bin'
            with patch('mx700_studio.ui.QFileDialog.getSaveFileName', return_value=(str(target), '')):
                self.assertTrue(window.save_copy())
            self.assertEqual(len(target.read_bytes()), len(original))
            differences = [i for i, (old, new) in enumerate(zip(original, target.read_bytes())) if old != new]
            self.assertLessEqual(len(differences), 7)
            self.assertGreater(len(differences), 0)
            self.assertEqual(source.read_bytes(), original)
            self.assertFalse(window.document.dirty)
            window.close()

    def test_read_worker_saves_backup_without_write_protocol(self):
        from mx700_studio.raw_memory import RawMemoryDocument
        data = bytearray(8192)
        data[2] = 0x0a
        data[0x97:0x9c] = b'MAIN '
        data[0x17b5:0x17b5 + 50] = b' ' * 50
        seal_system(data)
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'read.bin'
            worker = ReadWorker('/dev/fake-test-port', target)
            errors, results = [], []
            worker.failed.connect(errors.append)
            worker.succeeded.connect(results.append)
            with patch('mx700_studio.ui.SerialPort') as port:
                with patch('mx700_studio.ui.RemoteReader') as reader:
                    reader.return_value.read_configuration.return_value = bytes(data)
                    worker.run()
                    port.assert_called_once_with('/dev/fake-test-port')
                    reader.return_value.read_configuration.assert_called_once()
            self.assertEqual(errors, [])
            self.assertEqual(results, [str(target)])
            self.assertEqual(target.read_bytes(), data)
            self.assertEqual(RawMemoryDocument.load(target).devices[0].name, 'MAIN')
            with patch('mx700_studio.ui.SerialPort') as port:
                worker.run()
                port.assert_not_called()
            self.assertEqual(len(errors), 1)
            self.assertEqual(target.read_bytes(), data)

    def test_write_worker_success_and_failure_never_retry(self):
        from mx700_studio.sync import SourceChangedError
        for failure in (None, SourceChangedError('Source changed; nothing written'), RuntimeError('Link interrupted')):
            worker = WriteWorker('/dev/fake', b'original', b'edited', '/tmp/edited-test.bin')
            errors, results = [], []
            worker.failed.connect(errors.append)
            worker.succeeded.connect(results.append)
            with patch('mx700_studio.ui.SerialPort'):
                with patch('mx700_studio.ui.apply_label_changes', side_effect=failure) as apply:
                    worker.run()
                    apply.assert_called_once()
                    self.assertEqual(apply.call_args.args[1:], (b'original', b'edited'))
            if failure is None:
                self.assertEqual(results, ['/tmp/edited-test.bin'])
                self.assertEqual(errors, [])
            else:
                self.assertEqual(results, [])
                self.assertEqual(len(errors), 1)
                if not isinstance(failure, SourceChangedError):
                    self.assertIn('No retry', errors[0])

    @patch('mx700_studio.ui.HARDWARE_LABEL_WRITES_ENABLED', True)
    def test_write_action_saves_copy_before_starting_transfer(self):
        data = bytearray(8192)
        data[2] = 0x0a
        data[0x97:0x9c] = b'MAIN '
        data[0x17b5:0x17b5 + 50] = b' ' * 50
        with tempfile.TemporaryDirectory() as temp:
            source, target = Path(temp) / 'original.bin', Path(temp) / 'edited.bin'
            source.write_bytes(seal_system(data))
            window = MainWindow(source)
            window.label_edit.setText('TV')
            window.apply_label()
            with patch('mx700_studio.ui.available_ports', return_value=['/dev/fake']):
                with patch('mx700_studio.ui.QFileDialog.getSaveFileName', return_value=(str(target), '')):
                    with patch('mx700_studio.ui.QMessageBox.question', return_value=QMessageBox.Yes):
                        with patch('mx700_studio.ui.WriteWorker') as worker:
                            worker.return_value.start.side_effect = lambda: self.assertTrue(target.exists())
                            window.write_labels()
                            worker.return_value.start.assert_called_once()
                            self.assertEqual(worker.call_args.args[1], bytes(data))
                            self.assertEqual(worker.call_args.args[2], target.read_bytes())
            self.assertEqual(source.read_bytes(), data)
            window._worker = None
            window.close()
