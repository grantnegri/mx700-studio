"""Evidence-based fixed-slot MX700 macro codec. All edits are offline copies.

Device macros use 21 checksummed 8 KiB banks at remote 0x28000.
See docs/macros.md for disassembly evidence and supported boundaries.
"""
from dataclasses import dataclass

BACKUP_SIZE = 0x73000
MACRO_FILE_OFFSET = 0x1F000
BANK_SIZE = 0x2000
RECORD_SIZE = 190
RECORD_COUNT = 43


@dataclass(frozen=True)
class MacroStep:
    kind: str
    value: int
    device_slot: int
    offset: int  # offset within record
    size: int

    @property
    def tenths(self):
        return self.value if self.kind == "delay" else None


@dataclass(frozen=True)
class MacroRecord:
    device_slot: int
    index: int
    offset: int  # full backup file offset
    before: bool
    steps: tuple[MacroStep, ...]
    raw: bytes
    used: int

    @property
    def active(self):
        return self.raw[:2] != b"\xff\xff"

    @property
    def key_id(self):
        return 0 if self.index == 0 else 35 if self.index == 1 else 76 if self.index == 42 else self.index + 34


def _bank(data, device_slot):
    if len(data) != BACKUP_SIZE:
        raise ValueError("Macro editing requires a complete 471040-byte backup")
    if type(device_slot) is not int or not 0 <= device_slot <= 20:
        raise ValueError("Device slot must be 0..20")
    offset = MACRO_FILE_OFFSET + BANK_SIZE * device_slot
    bank = data[offset:offset + BANK_SIZE]
    if bank[2] != 0x28 + device_slot * 2:
        raise ValueError("Unexpected macro bank identity")
    if int.from_bytes(bank[:2], "big") != (0x852 + sum(bank[2:])) & 0xffff:
        raise ValueError("Invalid macro bank checksum")
    return offset, bank


def get_macro(data: bytes, device_slot: int, index: int) -> MacroRecord:
    """Decode one fixed record, retaining command IDs and context selections."""
    base, bank = _bank(data, device_slot)
    if type(index) is not int or not 0 <= index < RECORD_COUNT:
        raise ValueError("Macro index must be 0..42")
    start = 3 + index * RECORD_SIZE
    raw = bytes(bank[start:start + RECORD_SIZE])
    before = raw[0] == 255
    if raw[:2] == b"\xff\xff":
        return MacroRecord(device_slot, index, base + start, before, (), raw, 0)
    pos = 1 if before else 0
    current = device_slot
    steps = []
    while pos < RECORD_SIZE and raw[pos] != 255:
        token = raw[pos]
        begin = pos
        pos += 1
        if token >= 192:
            if token == 254:
                raise ValueError("Reserved delay token FE is not emitted by this editor")
            value = token & 63
            # The editor folds a following delay into any max-sized chunk.
            while token == 253 and pos < RECORD_SIZE and 192 <= raw[pos] < 254:
                token = raw[pos]
                value += token & 63
                pos += 1
            steps.append(MacroStep("delay", value, current, begin, pos - begin))
        elif token >= 160:
            page = token & 31
            if page > 3:
                raise ValueError("Unsupported macro page jump")
            steps.append(MacroStep("page", page, current, begin, 1))
        elif token >= 128:
            current = token & 31
            if current > 20:
                raise ValueError("Unsupported macro device selector")
            steps.append(MacroStep("device", current, current, begin, 1))
        else:
            if token > 76:
                raise ValueError("Unsupported macro command ID")
            steps.append(MacroStep("command", token, current, begin, 1))
    if pos == RECORD_SIZE:
        raise ValueError("Macro record has no terminator")
    return MacroRecord(device_slot, index, base + start, before, tuple(steps), raw, pos)


def parse_macros(data: bytes, *, include_empty=False) -> tuple[MacroRecord, ...]:
    records = []
    for device_slot in range(21):
        for index in range(RECORD_COUNT):
            macro = get_macro(data, device_slot, index)
            if macro.active or include_empty:
                records.append(macro)
    return tuple(records)


def _delay_bytes(tenths):
    if type(tenths) is not int or not 1 <= tenths <= 300:
        raise ValueError("Delay must be 1..300 tenths of a second")
    full, remainder = divmod(tenths, 61)
    return b"\xfd" * full + (bytes([0xc0 | remainder]) if remainder else b"")


def _splice(data, macro, start, size, replacement):
    if not macro.active:
        raise ValueError("Create new macros through a separate assignment-aware operation")
    if any(byte != 255 for byte in macro.raw[macro.used:]):
        raise ValueError("Cannot shift a macro with opaque trailing data")
    payload = macro.raw[:start] + replacement + macro.raw[start + size:macro.used]
    # Leave at least one FF terminator; do not reproduce editor's overrun path.
    if len(payload) >= RECORD_SIZE:
        raise ValueError("Macro exceeds its 190-byte record capacity")
    output = bytearray(data)
    output[macro.offset:macro.offset + RECORD_SIZE] = payload.ljust(RECORD_SIZE, b"\xff")
    bank_start = MACRO_FILE_OFFSET + macro.device_slot * BANK_SIZE
    checksum = (0x852 + sum(output[bank_start + 2:bank_start + BANK_SIZE])) & 0xffff
    output[bank_start:bank_start + 2] = checksum.to_bytes(2, "big")
    result = bytes(output)
    get_macro(result, macro.device_slot, macro.index)
    return result


def set_delay(data: bytes, device_slot: int, index: int, step_index: int, tenths: int) -> bytes:
    """Replace an existing delay, preserving all other tokens and banks."""
    macro = get_macro(data, device_slot, index)
    if type(step_index) is not int or not 0 <= step_index < len(macro.steps):
        raise ValueError("Invalid step index")
    step = macro.steps[step_index]
    if step.kind != "delay":
        raise ValueError("Selected step is not a delay")
    return _splice(data, macro, step.offset, step.size, _delay_bytes(tenths))


def insert_delay(data: bytes, device_slot: int, index: int, before_step: int, tenths: int) -> bytes:
    """Insert a delay before a decoded step, or append at len(steps)."""
    macro = get_macro(data, device_slot, index)
    if type(before_step) is not int or not 0 <= before_step <= len(macro.steps):
        raise ValueError("Invalid insertion point")
    offset = macro.steps[before_step].offset if before_step < len(macro.steps) else macro.used
    return _splice(data, macro, offset, 0, _delay_bytes(tenths))


def remove_delay(data: bytes, device_slot: int, index: int, step_index: int) -> bytes:
    macro = get_macro(data, device_slot, index)
    if type(step_index) is not int or not 0 <= step_index < len(macro.steps):
        raise ValueError("Invalid step index")
    step = macro.steps[step_index]
    if step.kind != "delay":
        raise ValueError("Selected step is not a delay")
    if len(macro.steps) == 1:
        raise ValueError("Cannot remove the sole macro action")
    return _splice(data, macro, step.offset, step.size, b"")


def validate_delay_changes(original: bytes, edited: bytes) -> tuple[int, ...]:
    """Validate a macro-only offline edit; return changed device slots.

    Accepts only delay insertions/removals/replacements in existing records,
    with unchanged command/context/page bytes, mode and opaque metadata.
    Intended as one component of a coordinated multi-section validator.
    """
    if len(original) != BACKUP_SIZE or len(edited) != BACKUP_SIZE:
        raise ValueError("Macro editing requires a complete backup")
    end = MACRO_FILE_OFFSET + 21 * BANK_SIZE
    if original[:MACRO_FILE_OFFSET] != edited[:MACRO_FILE_OFFSET] or original[end:] != edited[end:]:
        raise ValueError("Changes outside macro banks")
    changed_slots = []
    for slot in range(21):
        base, before_bank = _bank(original, slot)
        _, after_bank = _bank(edited, slot)
        if before_bank == after_bank:
            continue
        if before_bank[2] != after_bank[2] or before_bank[3 + RECORD_COUNT * RECORD_SIZE:] != after_bank[3 + RECORD_COUNT * RECORD_SIZE:]:
            raise ValueError("Changes to macro metadata")
        changed_record = False
        for index in range(RECORD_COUNT):
            before = get_macro(original, slot, index)
            after = get_macro(edited, slot, index)
            if before.raw == after.raw:
                continue
            if not before.active or not after.active or before.before != after.before:
                raise ValueError("Macro assignment or execution mode changed")
            for record in (before, after):
                if any(b != 255 for b in record.raw[record.used:]):
                    raise ValueError("Opaque macro trailing data")
            strip = lambda rec: bytes(rec.raw[s.offset] for s in rec.steps if s.kind != 'delay')
            if strip(before) != strip(after):
                raise ValueError("Macro command, device or page steps changed")
            if any(s.kind == 'delay' and not 1 <= s.value <= 300 for s in after.steps):
                raise ValueError("Unsupported macro delay")
            changed_record = True
        if not changed_record:
            raise ValueError("Checksum-only macro change")
        changed_slots.append(slot)
    return tuple(changed_slots)
