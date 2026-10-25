"""Native editor interactions against the optional private remote backup."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from mx700_studio.raw_memory import RawMemoryDocument
from mx700_studio.programming_ui import ProgrammingDialog
from mx700_studio import macros, commands


class ProgrammingUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        path = Path(__file__).resolve().parents[2] / 'sr101-original-config.bin'
        if not path.exists():
            raise unittest.SkipTest('Private remote backup not bundled')
        cls.original = path.read_bytes()

    def setUp(self):
        self.document = RawMemoryDocument(self.original)
        self.dialog = ProgrammingDialog(self.document)
        self.warnings = patch('mx700_studio.programming_ui.QMessageBox.warning',
                              side_effect=AssertionError('Unexpected edit warning')).start()
        # Every operation in these tests must remain offline.
        self.reader = patch('mx700_studio.programming.RemoteReader',
                            side_effect=AssertionError('Unexpected hardware read')).start()
        self.writer = patch('mx700_studio.programming.RemoteWriter',
                            side_effect=AssertionError('Unexpected hardware write')).start()
        self.addCleanup(patch.stopall)
        self.addCleanup(self.dispose_dialog)

    def dispose_dialog(self):
        self.dialog.close()
        self.dialog.deleteLater()
        self.app.processEvents()

    def test_inventory_and_macro_display(self):
        self.assertEqual(len(self.dialog.inventory),240)
        self.assertEqual(self.dialog.devices.count(),5)
        self.assertEqual(self.dialog.macro_choice.count(),2)
        self.assertEqual(self.dialog.steps.rowCount(),5)
        self.assertIn('0.5 seconds',self.dialog.steps.item(1,1).text())
        self.assertFalse(self.dialog.set_delay_button.isEnabled())
        self.dialog.steps.selectRow(1)
        self.assertTrue(self.dialog.set_delay_button.isEnabled())
        self.assertEqual(self.dialog.delay.value(),0.5)

    def test_copy_main_up_and_undo(self):
        d=self.dialog
        d.devices.setCurrentIndex(d.devices.findData(20))
        row=next(i for i,c in enumerate(d.visible_commands) if c.key_id==20)
        d.buttons.selectRow(row)
        d.sources.setCurrentIndex(next(i for i in range(d.sources.count()) if d.sources.itemData(i)==(0,20)))
        d.copy_button.click()
        self.assertTrue(self.document.dirty)
        self.assertEqual(self.document.program_operations,[('copy_learned',(20,20,0,20))])
        expected=commands.copy_learned(self.original,20,20,0,20)
        self.assertEqual(self.document.data,expected)
        self.assertTrue(d.undo_button.isEnabled())
        d.undo_button.click()
        self.assertEqual(self.document.data,self.original)
        self.assertFalse(self.document.dirty)
        self.assertEqual(self.document.program_operations,[])
        self.assertFalse(d.undo_button.isEnabled())

    def test_second_macro_and_source_selection_are_retained(self):
        d=self.dialog
        source=next(i for i in range(d.sources.count()) if d.sources.itemData(i)==(0,20))
        d.sources.setCurrentIndex(source)
        d.macro_choice.setCurrentIndex(1)
        self.assertEqual(d.macro_choice.currentData(),(0,20))
        d.steps.selectRow(1)
        d.delay.setValue(1.0)
        d.set_delay_button.click()
        self.assertEqual(d.macro_choice.currentData(),(0,20))
        self.assertEqual(d.sources.currentData(),(0,20))
        self.assertEqual(macros.get_macro(self.document.data,0,20).steps[1].tenths,10)
        self.assertEqual(macros.get_macro(self.document.data,0,5).steps[1].tenths,5)
        self.assertIn('hold',d.macro_note.text().lower())
        d.undo_button.click()
        self.assertEqual(self.document.data,self.original)

    def test_macro_change_insert_remove_and_undo(self):
        d=self.dialog
        d.steps.selectRow(1)
        d.delay.setValue(1.2)
        d.set_delay_button.click()
        self.assertEqual(macros.get_macro(self.document.data,0,5).steps[1].tenths,12)
        changed=self.document.data
        d.steps.selectRow(2)
        d.delay.setValue(0.8)
        d.insert_delay_button.click()
        self.assertEqual([s.value for s in macros.get_macro(self.document.data,0,5).steps],
                         [40,12,8,40,5,40])
        inserted=self.document.data
        d.remove_delay_button.click()
        self.assertEqual(self.document.data,changed)
        d.undo_button.click()
        self.assertEqual(self.document.data,inserted)
        d.undo_button.click()
        self.assertEqual(self.document.data,changed)
        d.undo_button.click()
        self.assertEqual(self.document.data,self.original)
        self.assertFalse(self.document.dirty)
        self.assertEqual(self.document.program_operations,[])


if __name__=='__main__':unittest.main()
