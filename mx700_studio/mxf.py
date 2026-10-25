"""Experimental, lossless label inspection for observed MX Editor legacy/v37 text tables.

This is not a complete MXF decoder. Unknown bytes are retained verbatim. Label
replacement is constrained to existing storage; upload compatibility is untested.
"""
from dataclasses import dataclass, field
from pathlib import Path
import re


@dataclass
class LabelRecord:
    offset: int
    identifier: int
    text: str
    length: int
    flag: int


@dataclass
class Button:
    label: str
    description: str
    max_length: int
    offset: int
    record_id: int


@dataclass
class Page:
    name: str
    buttons: list[Button] = field(default_factory=list)


@dataclass
class Device:
    name: str
    pages: list[Page] = field(default_factory=list)
    offset: int = 0


class MxfFormatError(ValueError):
    pass


def _record(data: bytes, offset: int):
    if offset + 13 > len(data) or data[offset:offset + 3] not in (b'\x16\x00\x07', b'\x16\x00\x70'):
        return None
    length = int.from_bytes(data[offset + 6:offset + 8], 'little') & 0x3ff
    if length >= 64:
        return None
    end = offset + 12 + length
    if end >= len(data) or data[end] != 0:
        return None
    raw = data[offset + 12:end]
    if any(c < 32 or c > 126 for c in raw):
        return None
    return LabelRecord(offset, int.from_bytes(data[offset+4:offset+6], 'little'),
                       raw.decode('ascii'), length, data[offset+3])


class MxfDocument:
    def __init__(self, data: bytes, path=None):
        self.path = Path(path) if path is not None else None
        self._original = bytes(data)
        self._data = bytearray(data)
        self._saved = bytes(data)
        self.devices = []
        self.records = []
        self._buttons = {}
        self.dirty = False
        self.layout = 'legacy-button-pairs'
        if data[:6] == bytes.fromhex('210025007000'):
            self.layout = 'modern-text-records'
            self._parse_modern(data)
            if not self.devices:
                raise MxfFormatError('No supported modern MXF text tables found')
            return
        # Anchor on paired device IDs, then walk records by their encoded length.
        # Do not scan arbitrary apparent text records inside metadata/payloads.
        for match in re.finditer(rb'\x16\x00\x07[\x00\x01]\x02\x80', data):
            start = match.start()
            first = _record(data, start)
            if first is None:
                continue
            second = _record(data, start + 13 + first.length)
            if second is None or second.identifier != 0x8001:
                continue
            records = []
            pos = start
            while (record := _record(data, pos)) is not None:
                records.append(record)
                pos += 13 + record.length
            if len(records) < 3 or not self._is_page(records[2].text):
                continue
            device = Device(first.text.rstrip(), offset=start)
            page = None
            pending = None
            for record in records[2:]:
                if self._is_page(record.text):
                    page = Page(record.text)
                    device.pages.append(page)
                    pending = None
                elif page is not None:
                    if pending is None:
                        pending = Button(record.text.rstrip(), '', record.length,
                                         record.offset + 12, record.identifier)
                        page.buttons.append(pending)
                        self._buttons[pending.offset] = pending
                    else:
                        pending.description = record.text.rstrip()
                        pending = None
            self.devices.append(device)
            self.records.extend(records)
        if not self.devices:
            raise MxfFormatError('No supported MXF device label groups found. This decoder supports only the observed legacy label layout.')

    def _parse_modern(self, data):
        # MX Editor v37 uses page-local text tables. Their order is unrelated to
        # physical button order. Expose individual records rather than inventing
        # a button/alternate-name mapping. Device-name tables terminate devices.
        runs = []
        consumed = 0
        for match in re.finditer(rb'\x16\x00\x70', data):
            start = match.start()
            if start < consumed:
                continue
            records = []
            pos = start
            while (record := _record(data, pos)) is not None:
                records.append(record)
                pos += 13 + record.length
            if records:
                consumed = pos
                runs.append(records)
        pages = []
        for records in runs:
            names = {r.identifier: r for r in records if r.identifier >= 0x8000}
            if 0x8002 in names:
                name = names.get(0x8001, names[0x8002]).text.rstrip()
                self.devices.append(Device(name, pages, records[0].offset))
                self.records.extend(records)
                pages = []
                continue
            headings = [r for r in records if self._is_page(r.text)]
            if len(headings) != 1:
                # Unknown table: do not expose as a fictional remote page.
                continue
            heading = headings[0]
            page = Page(heading.text + ' — text records')
            for record in records:
                if record is heading:
                    continue
                button = Button(record.text.rstrip(), f'Text ID {record.identifier}',
                                record.length, record.offset + 12, record.identifier)
                page.buttons.append(button)
                self._buttons[button.offset] = button
            pages.append(page)
            self.records.extend(records)

    @staticmethod
    def _is_page(text):
        return text == 'Hard Buttons' or re.fullmatch(r'Page [1-9][0-9]*', text) is not None

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
        if any(ord(c) < 32 or ord(c) > 126 for c in text):
            raise ValueError('Use printable ASCII characters only')
        if len(text) > button.max_length:
            raise ValueError(f'This label has space for {button.max_length} characters; expanding records is not yet supported')
        encoded = text.ljust(button.max_length).encode('ascii')
        self._data[button.offset:button.offset + button.max_length] = encoded
        button.label = text.rstrip()
        self.dirty = self._data != self._saved

    def save(self, path):
        target = Path(path)
        if self.path is not None and target.resolve() == self.path.resolve():
            raise ValueError('Choose a new file: the source MXF is kept intact')
        # Exclusive creation keeps Save As from silently replacing another file.
        with target.open('xb') as handle:
            handle.write(self._data)
        self._saved = bytes(self._data)
        self.dirty = False
        return target


# Convenient alternative spelling for callers.
Document = MxfDocument
