"""Native Qt interface for inspecting and conservatively editing MXF labels."""
from pathlib import Path
import sys

from PySide6.QtCore import Qt, Signal, QSize, QThread
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QKeySequence, QAction
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTreeWidget, QTreeWidgetItem, QSplitter, QFrame, QLineEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QFileDialog, QMessageBox,
    QAbstractItemView, QInputDialog,
)

from .mxf import MxfDocument
from .raw_memory import RawMemoryDocument
from .serial_port import SerialPort, available_ports
from .protocol import RemoteReader
from .sync import apply_label_changes, SourceChangedError

# Stored checksum recovered at MXM07M RVA 0x1b4d0; enforced by parser and writer.
HARDWARE_LABEL_WRITES_ENABLED = True

STYLE = """
QMainWindow, QWidget { background: #111b24; color: #e8eef2; font-family: 'DejaVu Sans'; font-size: 13px; }
QLabel#brand { font-size: 23px; font-weight: 700; }
QLabel#eyebrow { color: #71c9c0; font-size: 10px; font-weight: 700; }
QLabel#muted { color: #93a6b3; }
QLabel#section { font-size: 17px; font-weight: 700; }
QLabel#notice { background: #1c2a35; color: #aabcc8; padding: 12px; border-radius: 7px; }
QLabel#badge { background: #233630; color: #a6d8bb; padding: 6px 10px; border-radius: 5px; font-size: 11px; }
QFrame#panel { background: #17232e; border: 1px solid #2a3b48; border-radius: 10px; }
QFrame#panel QLabel, QFrame#panel QWidget { background: transparent; }
QPushButton { background: #233543; border: 1px solid #354c5c; border-radius: 6px; padding: 9px 15px; font-weight: 600; }
QPushButton:hover { background: #30495a; border-color: #70b5b1; }
QPushButton:disabled { color: #617580; background: #1b2833; border-color: #2a3945; }
QPushButton#primary { background: #71c9c0; color: #102b2a; border-color: #71c9c0; }
QPushButton#primary:hover { background: #90ded5; }
QPushButton#primary:disabled { background: #344d4c; color: #81908e; border-color: #344d4c; }
QTreeWidget, QTableWidget { background: #17232e; border: 0; outline: 0; alternate-background-color: #1b2a35; selection-background-color: #294c56; }
QTreeWidget::item { padding: 9px 5px; }
QTreeWidget::item:selected { background: #294c56; color: #dbfaf5; border-radius: 4px; }
QHeaderView::section { background: #20303d; color: #9fb3c0; border: 0; padding: 9px; font-size: 11px; }
QTableWidget::item { padding: 5px; border-bottom: 1px solid #22333f; }
QLineEdit { background: #101c25; border: 1px solid #405965; border-radius: 6px; padding: 11px; font-family: 'DejaVu Sans Mono'; font-size: 19px; }
QLineEdit:focus { border-color: #71c9c0; }
QLineEdit:disabled { color: #526672; border-color: #2a3945; }
QSplitter::handle { background: #111b24; width: 12px; }
QStatusBar { color: #93a6b3; background: #0e171f; }
QMenuBar, QMenu { background: #17232e; }
QToolTip { color: #e8eef2; background: #233543; border: 1px solid #405965; padding: 5px; }
"""


def label(text, name=None, wrap=False):
    widget = QLabel(text)
    if name:
        widget.setObjectName(name)
    widget.setWordWrap(wrap)
    return widget


class LcdPreview(QWidget):
    """Clickable layout preview. It does not simulate IR or remote operation."""
    selected = Signal(int)
    activated = Signal(int)

    def __init__(self):
        super().__init__()
        self.title = "OPEN MXF"
        self.labels = []
        self.active = -1
        self.setMinimumSize(270, 300)
        self.setMaximumHeight(335)
        self.setToolTip("Select a button to inspect it. Double-click to edit its label and programming.")

    def sizeHint(self):
        return QSize(340, 315)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        width = self.width()
        p.setPen(QPen(QColor('#435562'), 1))
        p.setBrush(QColor('#24343e'))
        p.drawRoundedRect(2, 2, width - 4, 294, 24, 24)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor('#a9b88b'))
        p.drawRoundedRect(38, 22, width - 76, 251, 9, 9)
        p.setPen(QColor('#344b30'))
        p.setFont(QFont('DejaVu Sans Mono', 15, QFont.Bold))
        p.drawText(42, 30, width - 84, 34, Qt.AlignCenter, self.title[:12].upper())
        p.setPen(QPen(QColor('#7a8b63'), 1))
        p.drawLine(52, 69, width - 52, 69)
        p.setFont(QFont('DejaVu Sans Mono', 15, QFont.Bold))
        for i in range(10):
            row, col = i // 2, i % 2
            y = 79 + row * 36
            x = 47 if col == 0 else width // 2 + 4
            text_width = width // 2 - 54
            if i == self.active:
                p.setBrush(QColor('#344b30'))
                p.setPen(Qt.NoPen)
                p.drawRoundedRect(x - 3, y, text_width + 6, 29, 3, 3)
            p.setPen(QColor('#d3e5b6') if i == self.active else QColor('#293e27'))
            text = self.labels[i] if i < len(self.labels) else '· · ·'
            align = Qt.AlignVCenter | (Qt.AlignLeft if col == 0 else Qt.AlignRight)
            p.drawText(x, y, text_width, 29, align, text[:7])
            p.setBrush(QColor('#536573'))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(13 if col == 0 else width - 31, y + 4, 18, 20, 4, 4)
        p.end()

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        index = self.hit_button(event.position().x(), event.position().y())
        if index is not None:
            self.selected.emit(index)

    def hit_button(self, x, y):
        row = int((y - 79) // 36)
        if 0 <= x < self.width() and 79 <= y < 259 and 0 <= row < 5:
            index = row * 2 + (1 if x >= self.width() / 2 else 0)
            if index < len(self.labels):
                return index
        return None

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            index = self.hit_button(event.position().x(), event.position().y())
            if index is not None:
                self.selected.emit(index)
                self.activated.emit(index)


class ReadWorker(QThread):
    progress = Signal(int, int)
    succeeded = Signal(str)
    failed = Signal(str)

    def __init__(self, port, target, parent=None):
        super().__init__(parent)
        self.port = port
        self.target = Path(target)

    def run(self):
        try:
            if self.target.exists():
                raise FileExistsError('Choose a new filename for the backup.')
            with SerialPort(self.port) as transport:
                data = RemoteReader(transport).read_configuration(self.progress.emit)
            with self.target.open('xb') as output:
                output.write(data)
            self.succeeded.emit(str(self.target))
        except Exception as error:
            self.failed.emit(str(error))


class WriteWorker(QThread):
    succeeded = Signal(str)
    failed = Signal(str)

    def __init__(self, port, original, edited, target, parent=None):
        super().__init__(parent)
        self.port, self.original, self.edited = port, original, edited
        self.target = str(target)

    def run(self):
        try:
            with SerialPort(self.port) as transport:
                apply_label_changes(transport, self.original, self.edited)
            self.succeeded.emit(self.target)
        except SourceChangedError as error:
            self.failed.emit(str(error))
        except Exception as error:
            self.failed.emit(f'{error}\n\nThe remote may have been partially updated. No retry was attempted. Preserve your original backup and read the remote again before another write.')


class ProgramWriteWorker(QThread):
    succeeded = Signal(str)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(self, port, original, edited, operations, target, parent=None):
        super().__init__(parent)
        self.port, self.original, self.edited = port, original, edited
        self.operations, self.target = tuple(operations), str(target)

    def run(self):
        from .programming import apply_program_changes
        try:
            with SerialPort(self.port) as transport:
                apply_program_changes(transport, self.original, self.edited,
                                      self.operations, self.progress.emit)
            self.succeeded.emit(self.target)
        except SourceChangedError as error:
            self.failed.emit(str(error))
        except Exception as error:
            self.failed.emit(f'{error}\n\nIf transfer began, the remote may be partially updated. No retry was attempted. Keep the original backup and read the remote before another write.')


class MainWindow(QMainWindow):
    def __init__(self, path=None):
        super().__init__()
        self.document = None
        self._worker = None
        self.source_path = None
        self.page = None
        self.button = None
        self.setMinimumSize(1000, 690)
        self.resize(1240, 820)
        self.setWindowTitle('MX700 Studio')
        self._build()
        if path:
            self.open_path(path)

    def _build(self):
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(26, 20, 26, 16)
        outer.setSpacing(18)
        head = QHBoxLayout()
        brand = QVBoxLayout()
        brand.setSpacing(4)
        brand.addWidget(label('B & K  /  MX-700 · SR 10.1', 'eyebrow'))
        brand.addWidget(label('MX700 Studio', 'brand'))
        head.addLayout(brand)
        head.addStretch()
        self.open_button = QPushButton('Open…')
        self.open_button.clicked.connect(self.open_dialog)
        head.addWidget(self.open_button)
        self.read_button = QPushButton('Read remote…')
        self.read_button.clicked.connect(self.read_remote)
        head.addWidget(self.read_button)
        self.program_button = QPushButton('Buttons and macros…')
        self.program_button.setEnabled(False)
        self.program_button.clicked.connect(self.program_buttons)
        head.addWidget(self.program_button)
        self.save_button = QPushButton('Save copy…')
        self.save_button.setObjectName('primary')
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self.save_copy)
        head.addWidget(self.save_button)
        self.write_button = QPushButton('Write labels…')
        self.write_button.setEnabled(False)
        self.write_button.clicked.connect(self.write_labels)
        head.addWidget(self.write_button)
        outer.addLayout(head)
        self.file_label = label('Open an MX Editor .mxf file to explore its devices and button labels.', 'muted')
        self.file_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        outer.addWidget(self.file_label)
        split = QSplitter(Qt.Horizontal)
        outer.addWidget(split, 1)
        nav = QFrame()
        nav.setObjectName('panel')
        nav_layout = QVBoxLayout(nav)
        nav_layout.setContentsMargins(16, 18, 12, 14)
        nav_layout.addWidget(label('Configuration', 'section'))
        self.count_label = label('No file loaded', 'muted')
        nav_layout.addWidget(self.count_label)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setMinimumWidth(190)
        self.tree.currentItemChanged.connect(self.select_tree_item)
        nav_layout.addWidget(self.tree, 1)
        split.addWidget(nav)
        center = QFrame()
        center.setObjectName('panel')
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(22, 18, 22, 18)
        title_row = QHBoxLayout()
        self.page_title = label('Remote layout', 'section')
        title_row.addWidget(self.page_title)
        title_row.addStretch()
        self.page_hint = label('LCD label preview', 'muted')
        title_row.addWidget(self.page_hint)
        center_layout.addLayout(title_row)
        self.preview = LcdPreview()
        self.preview.selected.connect(self.select_preview_button)
        self.preview.activated.connect(self.edit_layout_button)
        preview_row = QHBoxLayout()
        preview_row.addStretch()
        preview_row.addWidget(self.preview)
        preview_row.addStretch()
        center_layout.addLayout(preview_row)
        self.preview_note = label('Select a page to preview its labels.', 'muted', True)
        self.preview_note.setAlignment(Qt.AlignCenter)
        center_layout.addWidget(self.preview_note)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(['BUTTON LABEL', 'DESCRIPTION'])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.itemSelectionChanged.connect(self.select_table_button)
        self.table.cellDoubleClicked.connect(lambda row, column: self.edit_layout_button(row))
        center_layout.addWidget(self.table, 1)
        split.addWidget(center)
        inspector = QFrame()
        inspector.setObjectName('panel')
        inspector.setMinimumWidth(270)
        info = QVBoxLayout(inspector)
        info.setContentsMargins(20, 18, 20, 20)
        info.setSpacing(14)
        self.inspector_title = label('Button inspector', 'section')
        info.addWidget(self.inspector_title)
        self.selection_label = label('Select a button on the preview or in the list.', 'muted', True)
        info.addWidget(self.selection_label)
        info.addWidget(label('DISPLAY LABEL', 'eyebrow'))
        self.label_edit = QLineEdit()
        self.label_edit.setPlaceholderText('Button label')
        self.label_edit.setEnabled(False)
        self.label_edit.textChanged.connect(self.validate_edit)
        self.label_edit.returnPressed.connect(self.apply_label)
        info.addWidget(self.label_edit)
        self.capacity_label = label('Existing label capacity determines the edit limit.', 'muted', True)
        info.addWidget(self.capacity_label)
        self.apply_button = QPushButton('Apply label')
        self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(self.apply_label)
        info.addWidget(self.apply_button)
        self.edit_error = label('', 'muted', True)
        info.addWidget(self.edit_error)
        info.addStretch()
        self.mode_heading = label('EXPERIMENTAL FILE EDITING', 'eyebrow')
        info.addWidget(self.mode_heading)
        self.mode_notice = label('Shorter labels are padded with spaces. Other file bytes are preserved. Saved copies have not been validated on a physical remote.', 'muted', True)
        info.addWidget(self.mode_notice)
        info.addWidget(label('REMOTE TRANSFER', 'eyebrow'))
        info.addWidget(label('Read remote creates a backup. Save copy stays local. Write checks the original configuration and verifies readback. Buttons & macros opens the programming controls.', 'muted', True))
        split.addWidget(inspector)
        split.setSizes([235, 590, 300])
        self.workflow_notice = label('LOCAL FILE WORKSPACE     Open → inspect → edit labels → save a separate copy', 'notice')
        outer.addWidget(self.workflow_notice)
        self.statusBar().showMessage('Ready · No remote connection is made')
        menu = self.menuBar().addMenu('&File')
        action = QAction('&Open…', self, shortcut=QKeySequence.Open, triggered=self.open_dialog)
        menu.addAction(action)
        action = QAction('Save &copy…', self, shortcut=QKeySequence.SaveAs, triggered=self.save_copy)
        menu.addAction(action)
        menu.addSeparator()
        menu.addAction(QAction('&Quit', self, shortcut=QKeySequence.Quit, triggered=self.close))

    def confirm_discard(self):
        if self.document is None or not self.document.dirty:
            return True
        answer = QMessageBox.question(self, 'Unsaved changes', 'Save your configuration changes to a separate copy before continuing?', QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
        if answer == QMessageBox.Save:
            return self.save_copy()
        return answer == QMessageBox.Discard

    def open_dialog(self):
        if self._worker is not None and self._worker.isRunning():
            return
        path, _ = QFileDialog.getOpenFileName(self, 'Open MX Editor configuration', str(self.source_path.parent) if self.source_path else '', 'Remote configurations (*.mxf *.MXF *.dat *.DAT *.bin);;All files (*)')
        if path:
            self.open_path(path)

    def open_path(self, path, confirm=True):
        if confirm and not self.confirm_discard():
            return False
        try:
            document = RawMemoryDocument.load(path) if Path(path).suffix.lower() == '.bin' else MxfDocument.load(path)
        except Exception as error:
            QMessageBox.critical(self, 'Could not open configuration', str(error))
            return False
        self.document = document
        self.last_saved_path = None
        modern = document.layout == 'modern-text-records'
        readonly = getattr(document, 'readonly', False)
        raw = document.layout.startswith('remote-system-')
        self.mode_heading.setText('REMOTE MEMORY · LOCAL COPY' if raw else 'EXPERIMENTAL FILE EDITING')
        self.mode_notice.setText('Edit screen labels here. Buttons & macros lets you reassign existing commands, copy learned IR and change macro pauses from a full backup.' if raw else 'Shorter labels are padded with spaces. Other file bytes are preserved. Saved copies have not been validated on a physical remote.')
        self.workflow_notice.setText('REMOTE BACKUP WORKSPACE     Edit labels, buttons and pauses → save a copy → write and verify' if raw else 'LOCAL FILE WORKSPACE     Open → inspect → edit labels → save a separate copy')
        self.program_button.setEnabled(raw and len(document.data) == 0x73000)
        self.preview.setVisible(not modern)
        self.inspector_title.setText('Text inspector' if modern else 'Button inspector')
        self.table.setHorizontalHeaderLabels(['TEXT RECORD' if modern else 'BUTTON LABEL', 'ACTION / SIGNAL' if raw else 'IDENTIFIER' if modern else 'DESCRIPTION'])
        self.refresh_action_descriptions()
        self.source_path = Path(path).resolve()
        self.tree.clear()
        self.page = None
        self.button = None
        self.table.setRowCount(0)
        self.label_edit.clear()
        self.label_edit.setEnabled(False)
        self.preview.labels = []
        self.preview.title = 'NO PAGE'
        self.preview.active = -1
        self.preview.update()
        page_count = 0
        first = None
        for device in document.devices:
            item = QTreeWidgetItem([device.name.strip() or 'Unnamed device'])
            self.tree.addTopLevelItem(item)
            for page in device.pages:
                child = QTreeWidgetItem([page.name.strip() or 'Unnamed page'])
                child.setData(0, Qt.UserRole, (device, page))
                item.addChild(child)
                page_count += 1
                if first is None:
                    first = child
            item.setExpanded(True)
        self.count_label.setText(f'{len(document.devices)} devices · {page_count} pages')
        self.file_label.setText(self.source_path.name)
        self.file_label.setToolTip(str(self.source_path))
        self.save_button.setEnabled(not readonly)
        if first:
            self.tree.setCurrentItem(first)
        self.update_title()
        self.statusBar().showMessage('Loaded remote backup · Edits affect a local copy only' if raw else 'Loaded configuration · Original file remains unchanged')
        return True

    def select_tree_item(self, item, previous=None):
        if item is None:
            return
        data = item.data(0, Qt.UserRole)
        if not data:
            if item.childCount():
                self.tree.setCurrentItem(item.child(0))
            return
        device, self.page = data
        self.current_device = device
        self.page_title.setText(device.name.strip() or 'Device')
        self.page_hint.setText(self.page.name)
        self.preview.title = device.name.strip()
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.page.buttons))
        for row, button in enumerate(self.page.buttons):
            self.table.setItem(row, 0, QTableWidgetItem(button.label.rstrip()))
            summary, details = self.describe_button(button)
            cell = QTableWidgetItem(summary)
            cell.setToolTip(details)
            self.table.setItem(row, 1, cell)
        self.table.blockSignals(False)
        self.preview.labels = [b.label.rstrip() for b in self.page.buttons[:10]]
        self.preview.active = -1
        self.preview.update()
        if self.document.layout.startswith('remote-system-'):
            self.preview_note.setText('Double-click a screen button or list row to edit · Hover an action for full details')
        elif self.document.layout == 'modern-text-records':
            self.preview_note.setText('Text records from the original editor template.\nPhysical button mapping has not yet been decoded.')
        else:
            self.preview_note.setText('Label order preview; physical button positions are not yet verified.' if len(self.page.buttons) <= 10 else 'First 10 labels shown; all buttons are listed below.')
        self.button = None
        self.label_edit.clear()
        self.label_edit.setEnabled(False)
        if self.page.buttons:
            self.table.selectRow(0)
        else:
            self.selection_label.setText('This page contains no recognized labels.')
            self.apply_button.setEnabled(False)

    def select_preview_button(self, index):
        self.table.selectRow(index)

    def refresh_action_descriptions(self):
        self.action_descriptions = None
        self.action_description_error = ''
        if isinstance(self.document, RawMemoryDocument) and len(self.document.data) == 0x73000:
            from .actions import ActionDescriptions
            try:
                self.action_descriptions = ActionDescriptions(self.document.data)
            except ValueError as error:
                self.action_description_error = str(error)

    def button_key(self, button):
        page_index = self.current_device.pages.index(self.page)
        logical = button.record_id - 0x801
        if not hasattr(self.current_device, 'slot'):
            return page_index * 10 + logical, 76
        return self.current_device.slot, 36 + page_index * 10 + logical

    def describe_button(self, button):
        if self.action_descriptions is not None:
            slot,key = self.button_key(button)
            return (self.action_descriptions.describe_main(slot) if key == 76
                    else self.action_descriptions.describe(slot,key))
        if isinstance(self.document, RawMemoryDocument):
            return 'Signal unavailable', self.action_description_error or 'Read a complete remote backup to inspect button programming.'
        return (button.description or '—').split(';')[0], button.description

    def refresh_layout(self):
        row = self.table.currentRow()
        for index, device in enumerate(self.document.devices):
            self.tree.topLevelItem(index).setText(0, device.name.strip() or 'Unnamed device')
        self.refresh_action_descriptions()
        self.select_tree_item(self.tree.currentItem())
        if row >= 0: self.table.selectRow(row)
        self.update_title()

    def edit_layout_button(self, row):
        if self.page is None or not 0 <= row < len(self.page.buttons):
            return
        self.table.selectRow(row)
        button = self.page.buttons[row]
        if getattr(self.document, 'readonly', False):
            return
        if isinstance(self.document, RawMemoryDocument) and len(self.document.data) == 0x73000:
            from .programming_ui import ProgrammingDialog
            try:
                dialog = ProgrammingDialog(self.document, self, focus=self.button_key(button), label_button=button)
            except ValueError as error:
                QMessageBox.warning(self, 'Cannot inspect button programming', str(error))
                return
            dialog.exec()
            self.refresh_layout()
        else:
            text, accepted = QInputDialog.getText(self, 'Edit button label',
                f'Label (up to {button.max_length} characters):', text=button.label)
            if accepted:
                self.label_edit.setText(text)
                self.apply_label()

    def select_table_button(self):
        row = self.table.currentRow()
        if self.page is None or not (0 <= row < len(self.page.buttons)):
            return
        self.button = self.page.buttons[row]
        self.preview.active = row if row < 10 else -1
        self.preview.update()
        summary,details = self.describe_button(self.button)
        self.selection_label.setText(summary)
        self.selection_label.setToolTip(details)
        self.capacity_label.setText('Up to 5 ASCII characters. Changes stay in the local copy.' if self.document.layout.startswith('remote-system-') else f'Up to {self.button.max_length} ASCII characters. Shorter labels are padded.')
        self.label_edit.setMaxLength(max(1, self.button.max_length))
        self.label_edit.setEnabled(self.button.max_length > 0 and not getattr(self.document, 'readonly', False))
        self.label_edit.setText(self.button.label.rstrip())
        self.validate_edit()

    def validate_edit(self):
        if self.button is None or getattr(self.document, 'readonly', False):
            self.apply_button.setEnabled(False)
            return
        text = self.label_edit.text()
        valid = all(32 <= ord(c) <= 126 for c in text) and len(text) <= self.button.max_length
        self.edit_error.setText('Use printable ASCII characters only.' if not valid else '')
        self.apply_button.setEnabled(valid and text != self.button.label.rstrip())

    def apply_label(self):
        if self.button is None or not self.apply_button.isEnabled():
            return
        try:
            self.document.edit_label(self.button, self.label_edit.text())
        except Exception as error:
            QMessageBox.warning(self, 'Could not edit label', str(error))
            return
        for index, device in enumerate(self.document.devices):
            self.tree.topLevelItem(index).setText(0, device.name.strip() or 'Unnamed device')
        self.table.item(self.table.currentRow(), 0).setText(self.button.label.rstrip())
        self.preview.labels = [b.label.rstrip() for b in self.page.buttons[:10]]
        self.preview.update()
        self.validate_edit()
        self.refresh_layout()
        self.statusBar().showMessage('Label updated in memory · Save a copy to keep your changes')

    def update_title(self):
        programming = bool(getattr(self.document, 'program_operations', []))
        self.write_button.setText('Write changes…' if programming else 'Write labels…')
        self.write_button.setEnabled(HARDWARE_LABEL_WRITES_ENABLED and isinstance(self.document, RawMemoryDocument) and self.document.changed_byte_count > 0)
        self.write_button.setToolTip("Pending validation of edited system-section integrity" if not HARDWARE_LABEL_WRITES_ENABLED else "Write staged LCD label edits and verify readback")
        name = self.source_path.name if self.source_path else 'No file'
        self.setWindowTitle(f'{"● " if self.document and self.document.dirty else ""}{name} — MX700 Studio')

    def program_buttons(self):
        if not self.program_button.isEnabled():
            return
        from .programming_ui import ProgrammingDialog
        try:
            dialog = ProgrammingDialog(self.document, self)
        except ValueError as error:
            QMessageBox.warning(self, 'Unsupported programming data', str(error))
            return
        dialog.exec()
        self.refresh_layout()

    def save_copy(self):
        if self._worker is not None and self._worker.isRunning():
            return False
        if self.document is None or getattr(self.document, 'readonly', False):
            return False
        proposed = self.source_path.with_name(self.source_path.stem + '-edited' + self.source_path.suffix)
        path, _ = QFileDialog.getSaveFileName(self, 'Save a separate experimental copy', str(proposed), 'Remote configuration copies (*.mxf *.dat *.bin)')
        if not path:
            return False
        target = Path(path).expanduser().resolve()
        if not target.suffix:
            target = target.with_suffix(self.source_path.suffix or '.mxf')
        if target == self.source_path or (target.exists() and target.samefile(self.source_path)):
            QMessageBox.warning(self, 'Choose a separate file', 'The source configuration is preserved. Choose a different filename for the edited copy.')
            return False
        try:
            self.document.save(target)
            self.last_saved_path = target
        except Exception as error:
            QMessageBox.critical(self, 'Could not save copy', str(error))
            return False
        self.update_title()
        self.statusBar().showMessage(f'Saved copy: {target.name} · Physical remote validation is still required')
        return True

    def write_labels(self):
        if not HARDWARE_LABEL_WRITES_ENABLED:
            return
        if self._worker is not None and self._worker.isRunning():
            return
        if not isinstance(self.document, RawMemoryDocument) or not self.document.changed_byte_count:
            return
        ports = available_ports()
        if not ports:
            QMessageBox.information(self, 'No serial adapter found', 'Connect the remote programming cable and try again.')
            return
        port = ports[0]
        if len(ports) > 1:
            port, accepted = QInputDialog.getItem(self, 'Remote programming cable', 'Serial adapter:', ports, 0, False)
            if not accepted:
                return
        original, edited = bytes(self.document._original), self.document.data
        operations = getattr(self.document, 'program_operations', [])
        if operations:
            from .programming import validated_sections
            try:
                sections = validated_sections(original, edited, operations)
            except (ValueError, TypeError) as error:
                QMessageBox.warning(self, 'Cannot write changes', str(error))
                return
        count = sum(original[b.offset:b.offset + 5] != edited[b.offset:b.offset + 5]
                    for d in self.document.devices for p in d.pages for b in p.buttons)
        if not (self.last_saved_path and self.last_saved_path.exists() and self.last_saved_path.read_bytes() == edited):
            if not self.save_copy():
                return
        target = self.last_saved_path
        description = (f'Write {len(operations)} programming edit(s) and {count} label change(s) across {len(sections)} section(s)?\n\nButton/macro writes have simulated tests but have not yet been physically validated. The app compares and verifies the complete backup. Multiple sections are not an atomic transaction.' if operations else f'Write {count} changed LCD label(s) to the connected remote?\n\nThe app checks that the remote matches the original, writes the system section, and reads it back to verify.')
        answer = QMessageBox.question(self, 'Write configuration to the remote?',
            f'{description}\n\nOriginal backup: {self.source_path}\nEdited copy: {target}\n\nKeep the cable connected until completion.',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        self.centralWidget().setEnabled(False)
        self.statusBar().showMessage('Checking source, writing changes, and verifying… Keep the cable connected.')
        worker = ProgramWriteWorker(port, original, edited, operations, target, self) if operations else WriteWorker(port, original, edited, target, self)
        if operations:
            worker.progress.connect(self.statusBar().showMessage)
        self._worker = worker
        worker.succeeded.connect(self.write_succeeded)
        worker.failed.connect(self.write_failed)
        worker.finished.connect(self.read_finished)
        worker.start()

    def write_succeeded(self, path):
        self.open_path(path, confirm=False)
        self.statusBar().showMessage('Changes written and readback verified · Original backup preserved')

    def write_failed(self, error):
        self.statusBar().showMessage('Write did not complete with verification · No automatic retry')
        QMessageBox.critical(self, 'Remote write not verified', error)

    def read_remote(self):
        if self._worker is not None and self._worker.isRunning():
            return
        if not self.confirm_discard():
            return
        ports = available_ports()
        if not ports:
            QMessageBox.information(self, 'No serial adapter found', 'Connect the remote programming cable and try again.')
            return
        port = ports[0]
        if len(ports) > 1:
            port, accepted = QInputDialog.getItem(self, 'Remote programming cable', 'Serial adapter:', ports, 0, False)
            if not accepted:
                return
        path, _ = QFileDialog.getSaveFileName(self, 'Save a new complete remote backup', 'sr101-backup.bin', 'Remote memory backup (*.bin)')
        if not path:
            return
        target = Path(path).expanduser()
        if not target.suffix:
            target = target.with_suffix('.bin')
        if target.exists():
            QMessageBox.warning(self, 'Choose a new file', 'The backup must use a new filename. Existing files are preserved.')
            return
        self.centralWidget().setEnabled(False)
        self.statusBar().showMessage('Reading remote… Keep the programming cable connected.')
        worker = ReadWorker(port, target, self)
        self._worker = worker
        worker.progress.connect(lambda done, total: self.statusBar().showMessage(f'Reading remote: {done}/{total} chunks · Keep the cable connected'))
        worker.succeeded.connect(lambda path: self.open_path(path, confirm=False))
        worker.failed.connect(self.read_failed)
        worker.finished.connect(self.read_finished)
        worker.start()

    def read_failed(self, error):
        self.statusBar().showMessage('Remote read failed · Configuration was not written')
        QMessageBox.critical(self, 'Could not read remote', error)

    def read_finished(self):
        self.centralWidget().setEnabled(True)
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None

    def closeEvent(self, event):
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(self, 'Remote transfer in progress', 'Wait for the current transfer to finish before closing this window.')
            event.ignore()
            return
        if self.confirm_discard():
            event.accept()
        else:
            event.ignore()


def main(argv=None):
    args = sys.argv if argv is None else argv
    app = QApplication(args)
    app.setApplicationName('MX700 Studio')
    app.setOrganizationName('MX700 Studio')
    app.setStyle('Fusion')
    app.setStyleSheet(STYLE)
    window = MainWindow(args[1] if len(args) > 1 else None)
    window.show()
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
