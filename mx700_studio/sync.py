"""Apply only decoded LCD label edits, with fresh-source and readback checks."""
from .protocol import RemoteReader, RemoteWriter, ProtocolError
from .raw_memory import RawMemoryDocument, SYSTEM_SIZE


class SourceChangedError(ProtocolError):
    """The connected remote no longer matches the source backup."""


class ReadbackError(ProtocolError):
    """A completed write did not verify; remote state must be inspected."""


def apply_label_changes(transport, original: bytes, edited: bytes) -> bytes:
    """Apply changed exposed five-byte LCD labels and return verified section.

    Inputs are immutable system sections or full configuration images of equal
    size. All layout/diff validation precedes serial I/O. A fresh read must equal
    the original system section before the fixed-section write. Final readback
    must equal the desired section exactly. No automatic retries or rollback
    occur after a write failure or mismatch. The caller owns port lifecycle.
    """
    if not isinstance(original, bytes) or not isinstance(edited, bytes):
        raise TypeError('Original and edited images must be immutable bytes')
    if len(original) != len(edited):
        raise ValueError('Original and edited images must have identical sizes')
    source = RawMemoryDocument(original)
    RawMemoryDocument(edited)  # validate signature, layout and printable labels
    allowed = {i for offset in source._buttons for i in range(offset, offset + 5)}
    changed = {i for i, (before, after) in enumerate(zip(original, edited)) if before != after}
    if not changed & allowed:
        raise ValueError('No label bytes changed')
    # Section checksum bytes are derived metadata, validated by the document.
    checksum_offsets = {source.section_file_offset, source.section_file_offset + 1}
    if not changed <= allowed | checksum_offsets:
        raise ValueError('Changes outside exposed five-byte LCD label slots are not supported')
    offset = source.section_file_offset
    before = original[offset:offset + SYSTEM_SIZE]
    desired = edited[offset:offset + SYSTEM_SIZE]
    reader = RemoteReader(transport)
    if reader.read_blocks(0xA000, 0xB000) != before:
        raise SourceChangedError('Remote system section differs from the source backup; nothing was written')
    RemoteWriter(transport).write_system_section(desired)
    actual = reader.read_blocks(0xA000, 0xB000)
    if actual != desired:
        raise ReadbackError('System-section readback differs from the edited image; no automatic retry was attempted')
    return actual
