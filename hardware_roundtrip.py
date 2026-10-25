"""Explicit same-content system-write test against an existing complete backup.

Writes only the original 8192-byte system section, then rereads all configuration
bytes and compares them to the preserved backup. Never retries writes.
"""
import argparse
from pathlib import Path
from mx700_studio.protocol import CONFIG_SIZE, RemoteReader, RemoteWriter
from mx700_studio.raw_memory import RawMemoryDocument
from mx700_studio.serial_port import SerialPort


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('port')
    parser.add_argument('original_backup')
    parser.add_argument('--confirm-same-content-write', action='store_true', required=True)
    args = parser.parse_args()
    source = Path(args.original_backup)
    original = source.read_bytes()
    if len(original) != CONFIG_SIZE:
        parser.error('Requires complete original configuration backup')
    RawMemoryDocument(original)  # recognized layout before I/O
    system = original[0x1000:0x3000]
    with SerialPort(args.port) as port:
        reader = RemoteReader(port)
        current = reader.read_blocks(0xA000, 0xB000)
        if current != system:
            raise RuntimeError('Remote system differs from the backup; no write attempted')
        print('Fresh system read equals preserved backup. Writing identical system bytes.', flush=True)
        RemoteWriter(port).write_system_section(system)
        print('Write acknowledged; verifying the full configuration.', flush=True)
        after = reader.read_configuration(lambda done, total: print(f'Verified read {done}/{total}', flush=True))
    if after != original:
        recovery = source.with_name(source.stem + '-readback-mismatch.bin')
        with recovery.open('xb') as f:
            f.write(after)
        raise RuntimeError(f'Full readback differs; retained it at {recovery}. Do not retry automatically.')
    print(f'PASS: all {len(after)} configuration bytes are identical after the same-content write.', flush=True)


if __name__ == '__main__':
    main()
