"""Statically recovered SR10.1 upload (remote -> PC).

Reader plus restricted configuration-section writer; no erase or firmware API.
Addresses identify inclusive 4 KiB blocks. See docs/protocol.md for evidence.
"""
from __future__ import annotations
import time
from typing import Protocol

BLOCK_SIZE = 4096
EDITOR_BAUD = 115200

# Internal editor upload task ranges, inclusive byte ends (not wire opcodes).
CONFIG_SECTIONS = ((0x9000, 0xFFFF), (0x10000, 0x27FFF),
                   (0x28000, 0x51FFF), (0x52000, 0x7BFFF))
CONFIG_BASE = 0x9000
CONFIG_SIZE = 0x73000


def full_read_plan() -> tuple[tuple[int, int], ...]:
    """Original editor's 16 read requests, inclusive block addresses.

    MXM07M 0x10007250 supplies four sections; 0x10005cb0 chunks at 32 KiB.
    This is configuration memory, not a firmware or whole-flash dump.
    """
    return tuple((start, min(start + 0x8000, end + 1) - BLOCK_SIZE)
                 for first, end in CONFIG_SECTIONS
                 for start in range(first, end + 1, 0x8000))


class ProtocolError(Exception):
    pass


class Transport(Protocol):
    def write(self, data: bytes) -> int: ...
    def read(self, size: int, timeout: float) -> bytes: ...
    def reset_input_buffer(self) -> None: ...


def checksum(payload: bytes) -> bytes:
    """MXM07M.dll 0x1001afa0: sum seeded with 0x0852, high byte first."""
    return ((0x0852 + sum(payload)) & 0xFFFF).to_bytes(2, 'big')


def read_request(start_address: int, end_block_address: int) -> bytes:
    """Return command 04 for inclusive aligned block addresses, without I/O."""
    for address in (start_address, end_block_address):
        if type(address) is not int or not 0 <= address <= 0xFF000 or address % BLOCK_SIZE:
            raise ValueError('Addresses must be 4 KiB aligned and within 0x00000..0xFF000')
    if end_block_address < start_address:
        raise ValueError('End block must be at or after start block')
    first, last = start_address >> 12, end_block_address >> 12
    return bytes((4, first, last, first, last))


class RemoteReader:
    def __init__(self, transport: Transport, *, sleep=time.sleep):
        self.transport = transport
        self.sleep = sleep

    def read_configuration(self, progress=None):
        chunks = []
        plan = full_read_plan()
        for index, (start, end) in enumerate(plan):
            chunks.append(self.read_blocks(start, end))
            if progress:
                progress(index + 1, len(plan))
        return b''.join(chunks)

    def _write(self, data: bytes) -> None:
        if self.transport.write(data) != len(data):
            raise ProtocolError('Incomplete serial write')

    def wakeup(self) -> None:
        """Two AA attempts; preserve known MX700 response handling only."""
        self.transport.reset_input_buffer()
        seen_eb = False
        for _ in range(2):
            self._write(b'\xaa')
            reply = self.transport.read(1, 1.0)
            if reply == b'\xaa':
                return
            if reply == b'\xeb':
                if seen_eb:
                    return
                seen_eb = True
            elif reply not in (b'', b'\xa5', b'\xe1'):
                raise ProtocolError(f'Unexpected wakeup response: {reply.hex()}')
            self.sleep(0.1)
        raise ProtocolError('Remote did not complete wakeup handshake')

    def _read_exact(self, size: int, initial_timeout: float, subsequent_timeout: float) -> bytes:
        result = bytearray()
        while len(result) < size:
            part = self.transport.read(size - len(result), initial_timeout if not result else subsequent_timeout)
            if not part:
                raise ProtocolError(f'Serial timeout after {len(result)} of {size} bytes')
            if len(part) > size - len(result):
                raise ProtocolError('Transport returned more bytes than requested')
            result.extend(part)
        return bytes(result)

    def read_blocks(self, start_address: int, end_block_address: int) -> bytes:
        request = read_request(start_address, end_block_address)  # validate before touching serial
        size = (request[2] - request[1] + 1) * BLOCK_SIZE
        self.wakeup()
        self._write(request)
        payload = self._read_exact(size, 0.3, 0.2)
        actual = self._read_exact(2, 1.0, 1.0)
        expected = checksum(payload)
        self.sleep(0.2)
        if actual != expected:
            raise ProtocolError(f'Checksum mismatch: received {actual.hex()}, expected {expected.hex()}')
        return payload

class RemoteWriter:
    """Restricted configuration-section writer, recovered from the editor.

    Writes only known complete checksum sections. No automatic retry or rollback.
    Successful protocol completion still requires independent readback.
    """
    def __init__(self, transport: Transport, *, sleep=time.sleep):
        self.transport = transport
        self.sleep = sleep

    def write_system_section(self, payload: bytes) -> None:
        """Write exactly 8192 bytes using SectionDownloadSystemData's path.

        The transport must provide bounded drain_output(timeout). A failure
        after the command is sent leaves remote state uncertain; do not retry
        automatically. This method does not open ports or perform readback.
        """
        if not isinstance(payload, bytes) or len(payload) != 8192:
            raise ValueError('System section must be exactly 8192 immutable bytes')
        if payload[:2] != checksum(payload[2:]):
            raise ValueError('System section internal checksum is invalid')
        self._write_section(0xA000, payload, final_timeout=5.0, name='System')

    def write_configuration_section(self, start: int, payload: bytes) -> None:
        """Write one allowlisted section with a valid internal checksum.

        Supports shortcuts (9000), LCD/system (A000), and one macro slot
        (28000 + slot*2000) or learned IR slot (52000 + slot*2000),
        slots 0..20 in each bank. The original editor uses the
        data-download wrapper for macro/learned slots (4-second final ack), and
        program-download for shortcuts/system (5-second final ack).
        No arbitrary regions, concatenated slots, or firmware.
        Caller must compare source against a fresh read and verify afterward.
        """
        if type(start) is not int:
            raise ValueError('Configuration section address must be an integer')
        if start == 0x9000:
            size, final_timeout = 0x1000, 5.0
        elif start == 0xA000:
            size, final_timeout = 0x2000, 5.0
        elif 0x28000 <= start <= 0x50000 and (start - 0x28000) % 0x2000 == 0:
            size, final_timeout = 0x2000, 4.0
        elif 0x52000 <= start <= 0x7A000 and (start - 0x52000) % 0x2000 == 0:
            size, final_timeout = 0x2000, 4.0
        else:
            raise ValueError('Address is not an allowed configuration section')
        if not isinstance(payload, bytes) or len(payload) != size:
            raise ValueError(f'Configuration section must be exactly {size} immutable bytes')
        if payload[:2] != checksum(payload[2:]):
            raise ValueError('Configuration section internal checksum is invalid')
        self._write_section(start, payload, final_timeout=final_timeout, name='Configuration')

    def _write_section(self, start: int, payload: bytes, *, final_timeout: float, name: str) -> None:
        drain = getattr(self.transport, 'drain_output', None)
        if not callable(drain):
            raise TypeError('Writer transport requires bounded drain_output(timeout)')
        helper = RemoteReader(self.transport, sleep=self.sleep)
        helper.wakeup()
        request = read_request(start, start + len(payload) - BLOCK_SIZE)
        helper._write(b'\x03' + request[1:])
        ready = self.transport.read(1, 3.0)
        if ready != b'\x55':
            raise ProtocolError(f'{name} write ready acknowledgement failed: {ready.hex() or "timeout"}')
        for offset in range(0, len(payload), 1500):
            helper._write(payload[offset:offset + 1500])
            self.sleep(0.002)
        drain(30.0)
        # The remote returns the checksum; the host must NOT send a trailer.
        actual = helper._read_exact(2, 4.0, 4.0)
        expected = checksum(payload)
        if actual != expected:
            raise ProtocolError(f'{name} write checksum mismatch: received {actual.hex()}, expected {expected.hex()}')
        complete = self.transport.read(1, final_timeout)
        if complete != b'\x55':
            raise ProtocolError(f'{name} write completion acknowledgement failed: {complete.hex() or "timeout"}')
        self.sleep(0.1)
        self.transport.reset_input_buffer()
