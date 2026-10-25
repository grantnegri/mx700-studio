"""Native button assignment and existing-macro editor."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QTabWidget, QWidget, QComboBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QPushButton, QDoubleSpinBox, QMessageBox,
    QLineEdit, QPlainTextEdit)
from . import commands, macros
from .programming import edit


def table(headers):
    result = QTableWidget(0, len(headers))
    result.setHorizontalHeaderLabels(headers)
    result.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    result.verticalHeader().hide()
    result.setSelectionBehavior(QAbstractItemView.SelectRows)
    result.setSelectionMode(QAbstractItemView.SingleSelection)
    result.setEditTriggers(QAbstractItemView.NoEditTriggers)
    return result


def choice_index(combo, value):
    # Qt QVariant lookup does not reliably compare Python tuple item data.
    return next((i for i in range(combo.count()) if combo.itemData(i) == value), -1)


class ProgrammingDialog(QDialog):
    def __init__(self, document, parent=None, *, focus=None, label_button=None):
        super().__init__(parent)
        self.document = document
        self.history = []
        self.context_key = focus
        self.label_button = label_button
        if not hasattr(document, 'program_operations'):
            document.program_operations = []
        self.setWindowTitle('Buttons and macros — MX700 Studio')
        self.resize(1000, 760)
        outer = QVBoxLayout(self)
        intro = QLabel('Program existing buttons and tune macro pauses. Changes stay in your working copy until you save and write them.')
        intro.setWordWrap(True)
        outer.addWidget(intro)
        if label_button is not None:
            title = QLabel('DISPLAY LABEL')
            outer.addWidget(title)
            label_row = QHBoxLayout()
            self.context_label = QLineEdit(label_button.label)
            self.context_label.setMaxLength(label_button.max_length)
            label_row.addWidget(self.context_label)
            self.context_apply = QPushButton('Apply label')
            self.context_apply.clicked.connect(self.apply_context_label)
            self.context_label.returnPressed.connect(self.apply_context_label)
            label_row.addWidget(self.context_apply)
            outer.addLayout(label_row)
            self.action_details = QPlainTextEdit()
            self.action_details.setReadOnly(True)
            self.action_details.setMaximumHeight(150)
            outer.addWidget(self.action_details)
        tabs = QTabWidget()
        self.tabs = tabs
        outer.addWidget(tabs)
        buttons = QWidget()
        bl = QVBoxLayout(buttons)
        self.devices = QComboBox()
        bl.addWidget(self.devices)
        self.buttons = table(['TARGET BUTTON', 'CURRENT ASSIGNMENT'])
        bl.addWidget(self.buttons)
        bl.addWidget(QLabel('Source command to use on the selected target button'))
        self.sources = QComboBox()
        self.sources.setMinimumContentsLength(60)
        bl.addWidget(self.sources)
        actions = QHBoxLayout()
        self.copy_button = QPushButton('Copy learned IR to target')
        self.copy_button.clicked.connect(lambda: self.assign('copy_learned'))
        self.link_button = QPushButton('Assign shortcut to target')
        self.link_button.clicked.connect(lambda: self.assign('assign_shortcut'))
        actions.addWidget(self.copy_button)
        actions.addWidget(self.link_button)
        bl.addLayout(actions)
        note = QLabel('Copy transfers an existing learned signal. Shortcut points to an existing command. Buttons with macros cannot be reassigned here. Built-in/default does not prove that a button emits a useful signal.')
        note.setWordWrap(True)
        bl.addWidget(note)
        tabs.addTab(buttons, 'Button assignments')
        macro_tab = QWidget()
        ml = QVBoxLayout(macro_tab)
        self.macro_choice = QComboBox()
        ml.addWidget(self.macro_choice)
        self.steps = table(['STEP', 'ACTION'])
        ml.addWidget(self.steps)
        controls = QHBoxLayout()
        controls.addWidget(QLabel('Delay (seconds)'))
        self.delay = QDoubleSpinBox()
        self.delay.setDecimals(1)
        self.delay.setSingleStep(0.1)
        self.delay.setRange(0.1, 30.0)
        self.delay.setValue(0.5)
        controls.addWidget(self.delay)
        self.set_delay_button = QPushButton('Change selected delay')
        self.set_delay_button.clicked.connect(lambda: self.change_delay('set_delay'))
        self.insert_delay_button = QPushButton('Insert before selected step')
        self.insert_delay_button.clicked.connect(lambda: self.change_delay('insert_delay'))
        self.remove_delay_button = QPushButton('Remove selected delay')
        self.remove_delay_button.clicked.connect(lambda: self.change_delay('remove_delay'))
        for button in (self.set_delay_button, self.insert_delay_button, self.remove_delay_button):
            controls.addWidget(button)
        ml.addLayout(controls)
        self.macro_note = QLabel('Existing macros only. A delay inserted as the first step requires holding the trigger button for that duration. Other pauses wait between actions. Command order and device selections are preserved.')
        self.macro_note.setWordWrap(True)
        ml.addWidget(self.macro_note)
        tabs.addTab(macro_tab, 'Macro delays')
        self.status = QLabel('No programming changes made in this window.')
        self.status.setWordWrap(True)
        outer.addWidget(self.status)
        foot = QHBoxLayout()
        self.undo_button = QPushButton('Undo last programming edit')
        self.undo_button.setEnabled(False)
        self.undo_button.clicked.connect(self.undo)
        foot.addWidget(self.undo_button)
        foot.addStretch()
        close = QPushButton('Done')
        close.clicked.connect(self.accept)
        foot.addWidget(close)
        outer.addLayout(foot)
        self.devices.currentIndexChanged.connect(self.refresh_buttons)
        self.macro_choice.currentIndexChanged.connect(self.refresh_steps)
        self.steps.itemSelectionChanged.connect(self.select_step)
        self.refresh()
        if focus is not None:
            self.devices.hide()
            self.buttons.hide()
            self.macro_choice.hide()
            title = (label_button.label or 'button') if label_button else self.command_name(*focus)
            self.setWindowTitle(f'Edit {title} — MX700 Studio')
            self.resize(1000,650)
            if label_button is not None:
                self.context_label.setFocus()
                self.context_label.selectAll()

    def apply_context_label(self):
        text = self.context_label.text()
        if text == self.label_button.label:
            return
        previous = self.document.data
        try:
            self.document.edit_label(self.label_button, text)
        except ValueError as error:
            QMessageBox.warning(self,'Cannot edit label',str(error))
            return
        self.history.append((previous,len(self.document.program_operations)))
        self.undo_button.setEnabled(True)
        self.refresh()
        self.status.setText('Label updated in the working copy.')

    def refresh(self):
        self.inventory = commands.inventory(self.document.data)
        self.command_map = {(c.device_slot,c.key_id): c for c in self.inventory}
        slot = self.devices.currentData()
        source = self.sources.currentData()
        self.devices.blockSignals(True)
        self.sources.blockSignals(True)
        self.devices.clear()
        self.sources.clear()
        seen = set()
        for c in self.inventory:
            if c.device_slot not in seen:
                self.devices.addItem(c.device_name, c.device_slot)
                seen.add(c.device_slot)
            if not c.macro:
                self.sources.addItem(f'{c.device_name} · {c.name} — {c.status}', (c.device_slot,c.key_id))
        self.devices.setCurrentIndex(max(0,self.devices.findData(slot)))
        self.sources.setCurrentIndex(max(0,choice_index(self.sources,source)))
        self.devices.blockSignals(False)
        self.sources.blockSignals(False)
        self.refresh_buttons()
        previous = self.macro_choice.currentData()
        self.macro_choice.blockSignals(True)
        self.macro_choice.clear()
        self.macro_records = macros.parse_macros(self.document.data)
        for m in self.macro_records:
            name = self.command_name(m.device_slot, m.key_id)
            self.macro_choice.addItem(name, (m.device_slot,m.index))
        self.macro_choice.setCurrentIndex(max(0,choice_index(self.macro_choice,previous)))
        self.macro_choice.blockSignals(False)
        self.refresh_steps()
        if self.context_key is not None:
            slot,key = self.context_key
            self.devices.setCurrentIndex(self.devices.findData(slot))
            row = next((i for i,c in enumerate(self.visible_commands) if c.key_id == key),-1)
            if row >= 0: self.buttons.selectRow(row)
            index = next((i for i,m in enumerate(self.macro_records) if (m.device_slot,m.key_id)==self.context_key),-1)
            if index >= 0: self.macro_choice.setCurrentIndex(index)
            self.tabs.setTabEnabled(0,row >= 0)
            self.tabs.setTabEnabled(1,index >= 0)
            self.tabs.setVisible(row >= 0 or index >= 0)
            self.tabs.setCurrentIndex(1 if index >= 0 else 0)
            self.refresh_context_details()

    def refresh_context_details(self):
        if self.label_button is None: return
        from .actions import ActionDescriptions
        descriptions = ActionDescriptions(self.document.data)
        slot,key = self.context_key
        summary,details = descriptions.describe_main(slot) if key == 76 else descriptions.describe(slot,key)
        self.action_details.setPlainText(summary + '\n\n' + details)
        self.context_label.setText(self.label_button.label)

    def command_name(self, device, key):
        c = self.command_map.get((device,key))
        return f'{c.device_name} · {c.name}' if c else f'Device {device} · button {key}'

    def refresh_buttons(self):
        key = self.visible_commands[self.buttons.currentRow()].key_id if hasattr(self,'visible_commands') and 0 <= self.buttons.currentRow() < len(self.visible_commands) else None
        self.visible_commands = [c for c in self.inventory if c.device_slot == self.devices.currentData()]
        self.buttons.setRowCount(len(self.visible_commands))
        for row,c in enumerate(self.visible_commands):
            status = c.status
            if status.startswith('Shortcut'):
                status = 'Shortcut → ' + self.command_name(c.target_device,c.target_key)
            self.buttons.setItem(row,0,QTableWidgetItem(c.name))
            self.buttons.setItem(row,1,QTableWidgetItem(status))
        if self.visible_commands:
            self.buttons.selectRow(next((i for i,c in enumerate(self.visible_commands) if c.key_id == key),0))

    def apply(self, operation, args):
        try:
            result = edit(self.document.data,operation,args)
        except ValueError as error:
            QMessageBox.warning(self,'Cannot apply this edit',str(error))
            return False
        if result == self.document.data:
            self.status.setText('The target already has that programming.')
            return False
        self.history.append((self.document.data,len(self.document.program_operations)))
        self.document._data = bytearray(result)
        self.document.program_operations.append((operation,tuple(args)))
        self.document.dirty = self.document.data != self.document._saved
        self.undo_button.setEnabled(True)
        self.refresh()
        self.status.setText(f'{len(self.document.program_operations)} programming edit(s) staged. Use Save copy and Write changes in the main window to apply them.')
        return True

    def assign(self, operation):
        row = self.buttons.currentRow()
        source = self.sources.currentData()
        if not 0 <= row < len(self.visible_commands) or source is None:
            return
        target = self.visible_commands[row]
        self.apply(operation,(target.device_slot,target.key_id,*source))

    def refresh_steps(self):
        pair = self.macro_choice.currentData()
        self.current_macro = macros.get_macro(self.document.data,*pair) if pair else None
        self.steps.setRowCount(len(self.current_macro.steps) if self.current_macro else 0)
        if self.current_macro:
            for row,s in enumerate(self.current_macro.steps):
                action = (f'Wait {s.value/10:.1f} seconds' if s.kind == 'delay' else
                          'Send ' + self.command_name(s.device_slot,s.value) if s.kind == 'command' else
                          f'Select device {s.value}' if s.kind == 'device' else f'Jump to page {s.value+1}')
                self.steps.setItem(row,0,QTableWidgetItem(str(row+1)))
                self.steps.setItem(row,1,QTableWidgetItem(action))
            if self.current_macro.steps: self.steps.selectRow(0)
        self.insert_delay_button.setEnabled(self.current_macro is not None)
        self.select_step()

    def select_step(self):
        row = self.steps.currentRow()
        step = self.current_macro.steps[row] if self.current_macro and 0 <= row < len(self.current_macro.steps) else None
        is_delay = step is not None and step.kind == 'delay'
        self.set_delay_button.setEnabled(is_delay)
        self.remove_delay_button.setEnabled(is_delay)
        if is_delay: self.delay.setValue(step.value/10)

    def change_delay(self, operation):
        if self.current_macro is None: return
        row = self.steps.currentRow()
        if row < 0: return
        args = (self.current_macro.device_slot,self.current_macro.index,row)
        if operation != 'remove_delay': args += (round(self.delay.value()*10),)
        if self.apply(operation,args):
            self.steps.selectRow(min(row,self.steps.rowCount()-1))

    def undo(self):
        if not self.history: return
        data,count = self.history.pop()
        self.document._data = bytearray(data)
        from .raw_memory import RawMemoryDocument
        restored = RawMemoryDocument(data)
        for offset,button in self.document._buttons.items():
            button.label = restored._buttons[offset].label
        for old,new in zip(self.document.devices,restored.devices):
            old.name = new.name
        del self.document.program_operations[count:]
        self.document.dirty = self.document.data != self.document._saved
        self.undo_button.setEnabled(bool(self.history))
        self.refresh()
        self.status.setText('Last programming edit undone. Original backup remains unchanged.')
