"""LCD label inspection and staged-copy edits for an SR10.1 system section.

Offsets and logical-column mapping verified against MXM07M.dll system-to-MXF
conversion (RVAs 0x185a0, 0x19510, 0x19770 and 0x1ae10). This is not an MXF
reconstruction: learned IR, macros, hard-button assignments and other sections
are deliberately not represented.
"""
from pathlib import Path
from .mxf import Device, Page, Button, MxfFormatError

SYSTEM_SIZE = 0x2000
LCD_BASE = 0x815
MAIN_BASE = 0x17b5


def section_checksum(data):
    """MXM07M RVA1b4d0: seed0852 plus section bytes2..end modulo65536."""
    return (0x852 + sum(data[2:])) & 0xffff


def _text(data, offset):
    raw = data[offset:offset + 5]
    if len(raw) != 5 or any(c < 32 or c > 126 for c in raw):
        raise MxfFormatError(f'Unsupported LCD characters at section offset 0x{offset:x}')
    return raw.decode('ascii').strip()


def _logical_offset(base, index):
    # Editor button IDs801..805 are right column;806..80a are left.
    return base + (index % 5) * 10 + (5 if index < 5 else 0)


class RawMemoryDocument:
    layout = 'remote-system-staged'
    readonly = False

    def __init__(self, data, path=None):
        self.path = Path(path) if path is not None else None
        self._original = bytes(data)
        self._data = bytearray(data)
        self._saved = bytes(data)
        self.dirty = False
        self._buttons = {}
        self.records = []
        self.devices = []
        self.section_file_offset = 0
        if len(data) == 0x73000:
            # Official upload extent9000..7bfff, system addressa000.
            self.section_file_offset = 0x1000
            data = data[0x1000:0x3000]
        elif len(data) != SYSTEM_SIZE:
            raise MxfFormatError('Expected an 8192-byte SR10.1 system section or 471040-byte configuration backup')
        if int.from_bytes(data[:2], 'big') != section_checksum(data):
            raise MxfFormatError('System-section checksum mismatch')
        if any(count > 4 for count in data[0x800:0x815]):
            raise MxfFormatError('Unsupported system-section page counts')
        main_count = 2 if data[0x814] >= 2 else 1
        main = Device(_text(data, 0x97) or 'MAIN', offset=0x97)
        main.pages = [self._page(data, MAIN_BASE + page * 50, page) for page in range(main_count)]
        self.devices.append(main)
        for slot in range(20):
            setup_word = int.from_bytes(data[3 + slot * 2:5 + slot * 2], 'little')
            if not (setup_word >> 5):
                continue
            page_count = data[0x800 + slot]
            if page_count > 4:
                raise MxfFormatError(f'Unsupported page count {page_count} for slot {slot}')
            name_offset = _logical_offset(MAIN_BASE + (slot // 10) * 50, slot % 10)
            name = _text(data, name_offset) or f'Device slot {slot}'
            device = Device(name, offset=name_offset)
            device.slot = slot
            device.pages = [self._page(data, LCD_BASE + slot * 200 + page * 50, page)
                            for page in range(page_count)]
            self.devices.append(device)
        for device in self.devices:
            for page in device.pages:
                for button in page.buttons:
                    button.offset += self.section_file_offset
                    self._buttons[button.offset] = button

    @staticmethod
    def _page(data, base, page_index):
        page = Page(f'Page {page_index + 1}')
        # Display physical row order; retain editor IDs in metadata.
        for physical in range(10):
            row, side = divmod(physical, 2)
            logical = row + (5 if side == 0 else 0)
            offset = base + physical * 5
            label = _text(data, offset)
            page.buttons.append(Button(label, f'{"Left" if side == 0 else "Right"} row {row + 1}; remote 0x{0xa000 + offset:x}',
                                       5, offset, 0x801 + logical))
        return page

    @classmethod
    def load(cls, path):
        path = Path(path)
        return cls(path.read_bytes(), path)

    @property
    def data(self):
        return bytes(self._data)

    @property
    def changed_byte_count(self):
        return sum(a != b for a, b in zip(self._original, self._data))

    def edit_label(self, button, text):
        if self._buttons.get(button.offset) is not button:
            raise ValueError('Button does not belong to this document')
        if len(text) > 5 or any(ord(c) < 32 or ord(c) > 126 for c in text):
            raise ValueError('LCD labels support at most 5 printable ASCII characters')
        encoded = (text.rjust(5) if button.record_id < 0x806 else text.ljust(5)).encode('ascii')
        self._data[button.offset:button.offset + 5] = encoded
        start = self.section_file_offset
        value = section_checksum(self._data[start:start + SYSTEM_SIZE])
        self._data[start:start + 2] = value.to_bytes(2, 'big')
        button.label = text.strip()
        for device in self.devices:
            if device.offset + self.section_file_offset == button.offset:
                device.name = text.strip() or f'Device slot {getattr(device, "slot", "?")}'
        self.dirty = self._data != self._saved

    def save(self, path):
        target = Path(path)
        if self.path is not None and target.resolve() == self.path.resolve():
            raise ValueError('Choose a new file: the original remote backup is kept intact')
        with target.open('xb') as handle:
            handle.write(self._data)
        self._saved = bytes(self._data)
        self.dirty = False
        return target
