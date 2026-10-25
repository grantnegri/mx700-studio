import argparse
import sys


def main():
    parser = argparse.ArgumentParser(description='Experimental native MX-700 / SR10.1 workbench')
    parser.add_argument('configuration', nargs='?', help='Raw .bin backup, supported .mxf, or factory .dat file to open')
    parser.add_argument('--ports', action='store_true', help='List Linux serial adapters without opening them')
    parser.add_argument('--probe', metavar='PORT', help='Experimental AA wake-up exchange; does not write configuration')
    parser.add_argument('--read-blocks', metavar='PORT', help='Experimental remote-to-PC raw memory read')
    parser.add_argument('--backup', metavar='PORT', help='Read the complete configuration memory range used by the original editor')
    parser.add_argument('--start', type=lambda v: int(v, 0), help='First 4 KiB block address (explicit, no default)')
    parser.add_argument('--end', type=lambda v: int(v, 0), help='Last 4 KiB block address, inclusive (explicit)')
    parser.add_argument('--output', help='New raw backup filename; never an MXF file')
    args = parser.parse_args()
    if args.ports:
        from .serial_port import available_ports
        ports = available_ports()
        print('\n'.join(ports) if ports else 'No USB serial adapters detected.')
        return 0
    if args.probe or args.read_blocks or args.backup:
        from .protocol import ProtocolError, RemoteReader, read_request
        from .serial_port import SerialPort
        if sum(bool(x) for x in (args.probe, args.read_blocks, args.backup)) > 1:
            parser.error('Choose one serial operation')
        if args.read_blocks:
            if args.start is None or args.end is None or not args.output:
                parser.error('--read-blocks requires --start, --end and --output; use --backup for the complete configuration')
            try:
                read_request(args.start, args.end)
            except ValueError as error:
                parser.error(str(error))
            from pathlib import Path
            if Path(args.output).exists():
                parser.error('Output already exists; choose a new backup filename')
        if args.backup:
            from pathlib import Path
            if not args.output or Path(args.output).exists():
                parser.error('--backup requires --output with a new filename')
        print('Native SR10.1 read protocol. This operation does not write configuration.', file=sys.stderr)
        try:
            with SerialPort(args.probe or args.read_blocks or args.backup) as port:
                reader = RemoteReader(port)
                if args.probe:
                    reader.wakeup()
                    print('Remote wake-up exchange succeeded. Configuration was not written.')
                else:
                    data = (reader.read_configuration(lambda done, total: print(f'Read {done}/{total} chunks', file=sys.stderr))
                            if args.backup else reader.read_blocks(args.start, args.end))
                    with open(args.output, 'xb') as f:
                        f.write(data)
                    print(f'Saved {len(data)} checksum-verified raw bytes to {args.output}. This is not an MXF configuration.')
        except (OSError, TimeoutError, ValueError, ProtocolError) as error:
            print(f'Transfer failed: {error}', file=sys.stderr)
            return 1
        return 0
    from .ui import main as gui_main
    return gui_main([sys.argv[0]] + ([args.configuration] if args.configuration else []))


if __name__ == '__main__':
    raise SystemExit(main())
