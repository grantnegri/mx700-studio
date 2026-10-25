"""Replay supported edits before allowing bounded configuration writes."""
from . import commands, macros
from .raw_memory import RawMemoryDocument
from .protocol import RemoteReader, RemoteWriter
from .sync import SourceChangedError, ReadbackError


EDITORS = {
    'assign_shortcut': commands.assign_shortcut,
    'copy_learned': commands.copy_learned,
    'set_delay': macros.set_delay,
    'insert_delay': macros.insert_delay,
    'remove_delay': macros.remove_delay,
}


def edit(data, operation, args):
    if operation not in EDITORS:
        raise ValueError('Unsupported programming operation')
    return EDITORS[operation](data, *args)


def validated_sections(original, edited, operations):
    if not isinstance(original, bytes) or not isinstance(edited, bytes):
        raise TypeError('Configuration images must be immutable bytes')
    if len(original) != 0x73000 or len(edited) != len(original):
        raise ValueError('Programming requires a complete remote backup')
    rebuilt = original
    for operation, args in operations:
        rebuilt = edit(rebuilt, operation, args)
    # Label edits may coexist with programming edits; replay only decoded slots.
    doc = RawMemoryDocument(rebuilt)
    target = RawMemoryDocument(edited)
    for offset, button in doc._buttons.items():
        if rebuilt[offset:offset+5] != edited[offset:offset+5]:
            doc.edit_label(button, target._buttons[offset].label)
    if doc.data != edited:
        raise ValueError('Image contains changes outside the recorded supported edits')
    ranges = [(0x9000, 0x1000), (0xa000, 0x2000)]
    ranges += [(base + slot*0x2000, 0x2000)
               for base in (0x28000, 0x52000) for slot in range(21)]
    sections = [(address, edited[address-0x9000:address-0x9000+size])
                for address, size in ranges
                if original[address-0x9000:address-0x9000+size] != edited[address-0x9000:address-0x9000+size]]
    if not sections:
        raise ValueError('No configuration changes to write')
    # Materialize learned codes before publishing any new shortcut routing.
    return sorted(sections, key=lambda item: item[0] == 0x9000)


def apply_program_changes(transport, original, edited, operations, progress=None):
    sections = validated_sections(original, edited, operations)
    reader = RemoteReader(transport)
    if progress: progress('Checking the complete remote against the original backup…')
    if reader.read_configuration() != original:
        raise SourceChangedError('Remote configuration differs from the original backup; nothing was written')
    writer = RemoteWriter(transport)
    for index, (address, payload) in enumerate(sections):
        if progress: progress(f'Writing section {index+1}/{len(sections)} at 0x{address:x}…')
        writer.write_configuration_section(address, payload)
    if progress: progress('Verifying the complete remote configuration…')
    actual = reader.read_configuration()
    if actual != edited:
        raise ReadbackError('Full configuration readback differs from the edited copy; no automatic retry was attempted')
    return actual
