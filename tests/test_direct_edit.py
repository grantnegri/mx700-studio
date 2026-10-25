"""Exercise actual Qt double-click routing without hardware or modal blocking."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from mx700_studio.commands import _update
from mx700_studio.programming_ui import ProgrammingDialog
from mx700_studio.ui import MainWindow
from test_actions import sample


class DirectEditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.source = Path(self.temp.name) / 'remote.bin'
        data = bytearray(sample())
        # Key39 has an action macro sending key40 twice with a pause.
        off = 0x1f000 + 3 + 5 * 190
        data[off:off+4] = bytes([40, 0xc5, 40, 255])
        _update(data, 0x1f000, 8192)
        a, b = 0x49000+3+17*106, 0x49000+3+40*106
        data[b:b+106] = data[a:a+106]
        _update(data, 0x49000, 8192)
        self.source.write_bytes(data)
        self.original = bytes(data)
        self.window = MainWindow(self.source)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        with patch.object(self.window, 'confirm_discard', return_value=True):
            self.window.close()
        self.temp.cleanup()

    def page(self, slot):
        index = next(i for i,d in enumerate(self.window.document.devices)
                     if getattr(d,'slot',20) == slot)
        self.window.tree.setCurrentItem(self.window.tree.topLevelItem(index).child(0))
        self.app.processEvents()

    def row(self, key):
        return next(i for i,b in enumerate(self.window.page.buttons)
                    if self.window.button_key(b)[1] == key)

    def double_click(self, row, surface, handler):
        dialogs = []
        def execute(dialog):
            dialogs.append(dialog)
            handler(dialog)
            return 0
        with patch.object(ProgrammingDialog, 'exec', execute):
            if surface == 'preview':
                pos = QPoint(self.window.preview.width() * (3 if row % 2 else 1) // 4,
                             79 + (row // 2) * 36 + 14)
                QTest.mouseDClick(self.window.preview, Qt.LeftButton, pos=pos)
            else:
                item = self.window.table.item(row, 1)
                self.window.table.scrollToItem(item)
                pos = self.window.table.visualItemRect(item).center()
                QTest.mouseClick(self.window.table.viewport(), Qt.LeftButton, pos=pos)
                QTest.mouseDClick(self.window.table.viewport(), Qt.LeftButton, pos=pos)
            self.app.processEvents()
        self.assertEqual(len(dialogs), 1, 'Double-click must open one editor')
        return dialogs[0]

    def test_simulator_and_table_focus_actual_button(self):
        self.page(0)
        for surface in ('preview', 'table'):
            row = self.row(40)
            dialog = self.double_click(row, surface, lambda d: None)
            self.assertEqual(dialog.context_key, (0,40))
            self.assertEqual(dialog.visible_commands[dialog.buttons.currentRow()].key_id,40)
            self.assertEqual(dialog.tabs.currentIndex(),0)
            self.assertIn('106-byte', dialog.action_details.toPlainText())

    def test_macro_focus_and_parent_sequence_refresh(self):
        self.page(0)
        row = self.row(39)
        self.assertIn('Wait 0.5s',self.window.table.item(row,1).text())
        captured = []
        def edit(dialog):
            captured.append((dialog.context_key, dialog.tabs.currentIndex(), dialog.macro_choice.currentData()))
            dialog.steps.selectRow(1)
            dialog.delay.setValue(1.2)
            dialog.set_delay_button.click()
        self.double_click(row, 'table', edit)
        self.assertEqual(captured, [((0,39),1,(0,5))])
        self.assertIn('Wait 1.2s', self.window.table.item(row,1).text())
        self.assertNotIn('Wait 0.5s', self.window.table.item(row,1).text())
        self.assertIn('106-byte', self.window.table.item(row,1).toolTip())
        self.assertEqual(self.source.read_bytes(),self.original)

    def test_main_selector_context_label_edit_and_undo(self):
        self.page(20)
        row = next(i for i,b in enumerate(self.window.page.buttons) if self.window.button_key(b)==(0,76))
        states = []
        def edit(dialog):
            states.append((dialog.context_key,dialog.tabs.isHidden(),dialog.action_details.toPlainText()))
            dialog.context_label.setText('AMP')
            dialog.context_apply.click()
            states.append((dialog.label_button.label, self.window.document.devices[1].name))
            dialog.undo_button.click()
            states.append(self.window.document.data)
        self.double_click(row,'preview',edit)
        self.assertEqual(states[0][:2],((0,76),True))
        self.assertIn('MAIN device selector',states[0][2])
        self.assertEqual(states[1],('AMP','AMP'))
        self.assertEqual(states[2],self.original)
        self.assertEqual(self.window.document.data,self.original)
        self.assertEqual(self.source.read_bytes(),self.original)

    def test_real_backup_layout_shows_ir_and_macro_instead_of_position(self):
        path = Path(os.environ.get('MX700_RAW_SAMPLE',Path(__file__).resolve().parents[2]/'sr101-original-config.bin'))
        if not path.exists(): self.skipTest('Private backup absent')
        self.window.open_path(path)
        self.page(0)
        texts = [self.window.table.item(i,1).text() for i in range(self.window.table.rowCount())]
        self.assertTrue(any('Wait 0.5s' in t for t in texts))
        self.assertTrue(any('IR ' in t for t in texts))
        self.assertFalse(any('row ' in t or 'remote 0x' in t for t in texts))
