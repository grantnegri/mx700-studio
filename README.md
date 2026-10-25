# MX700 Studio

Native Linux Qt application for the B&K SR10.1 / MX-700 family. It reads the remote configuration, edits LCD labels, reassigns existing button commands, copies learned IR signals, and adjusts pauses in existing macros. It does not require Windows, Wine, or an XP VM.

The current implementation is tested with the owner's SR10.1 and repaired FTDI FT232R cable. Other remote revisions are unverified. The full-backup programming editor exposes hard buttons and LCD commands. Creating devices, learning new signals from another remote, synthesizing IR codes, and creating/reordering macros are not implemented. Raw backups are not `.mxf` files.

## Run

Requires Linux and Python 3.10 or newer. Install from source:

```sh
git clone https://github.com/grantnegri/mx700-studio.git
cd mx700-studio
python3 -m venv .venv
.venv/bin/pip install -e .
./run.sh
# Or open an existing backup:
./run.sh /path/to/remote-backup.bin
```

Qt renders the desktop interface directly. The application uses Python's Linux serial APIs; Qt Essentials is its only GUI dependency. Run the application on the host when the cable is attached there.

## Use

1. Connect the working programming cable. **Read remote…** saves a new complete configuration backup and opens it. All 16 chunks must pass their checksums before the file is saved.
2. Select a device and page. **Double-click a button on the simulated screen or its list row** to edit that specific button's label and programming. Macro buttons open their macro editor; ordinary buttons open assignment controls. MAIN buttons show device selection and any entry macro. The **Action / signal** column shows sequences, waits, resolved shortcut targets or encoded learned-IR bytes; hover for full details. Stored IR records are not yet decoded into waveform/protocol values, and unknown built-in signals are explicitly marked. MAIN-page label edits also rename the corresponding device in the tree.
3. **Buttons and macros…** opens the full-backup programming editor. Choose a target device/button and a source command. **Copy learned IR to target** copies an existing signal; **Assign shortcut to target** routes to an existing command. The inventory distinguishes learned IR, shortcuts, macros, and built-in/default assignments. Built-in/default does not prove a useful IR command is present. Conflicting macros and unsafe changes are rejected.
4. In **Macro delays**, select an existing macro. Select a delay to change/remove it, or a step to insert a pause before it. Delays range from 0.1 to 30 seconds. A first-step delay creates a hold-to-activate requirement. **Undo last programming edit** reverses edits made in the current dialog; **Done** keeps them in the working copy.
5. **Save copy…** saves a separate binary; it does not program the remote. **Write changes…** saves first if needed, replays the supported edits for validation, compares the complete physical remote with the original backup, writes only affected sections, then compares the entire remote with the edited copy. Existing label-only transfers retain their narrower system-section check. No failed write is automatically retried. A multi-section write can leave a partial update if interrupted.

Keep the editing session open until you write: the programming operation history is currently held in memory, not saved in the binary. Reopening an edited copy treats it as a new baseline, not a pending change against the original remote. Preserve the original full backup. Programming writes are implemented and simulated-tested but changed-button/macro hardware behavior has not yet been validated.

The app also inspects the observed legacy MXF layout and the recovered B&K factory `.dat` template. Their file edits remain experimental and cannot be transferred through the raw-backup label writer. Some MXF labels can only be shortened or replaced at their existing length because record relocation is not implemented.

If Linux reports permission denied, grant access to the currently attached adapter in a host terminal:

```sh
sudo setfacl -m u:"$(id -un)":rw /dev/ttyUSB0
```

Use the actual device path reported on your system. This grant disappears when the adapter is unplugged; it does not install a persistent device rule.

## Command line

The read-only CLI does not require Qt to be imported:

```sh
.venv/bin/python -m mx700_studio --ports
.venv/bin/python -m mx700_studio --probe /dev/ttyUSB0
.venv/bin/python -m mx700_studio --backup /dev/ttyUSB0 --output new-backup.bin
```

The complete configuration image covers remote addresses `0x9000..0x7BFFF` and is 471,040 bytes. The 8,192-byte system section occupies file offsets `0x1000..0x2FFF`. This is the original editor's configuration upload range, not a firmware dump. Keep the complete original backup.

## Verification and reverse engineering

On October 25, 2026, native Linux code read the complete configuration and performed an approved same-content system write. A subsequent complete read matched all 471,040 original bytes. The native window was launched on the host with the real backup loaded. The expanded tests cover button/learned-code copying, shortcut overrides, macro delay edits, operation replay, bounded section writes, full readback, and native UI controls. No changed label, command or macro has been written to the physical remote during development.

Run the retained tests with:

```sh
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests -v
```

Tests cover byte-preserving edits, malformed inputs, source-file protection, packet framing, checksum errors, timeouts, rejected stale source data, write readback, native UI behavior, and a real POSIX pseudo-terminal. Simulated protocol tests are distinct from physical remote tests.

See [protocol findings](docs/protocol.md), [raw-memory layout](docs/raw-memory.md), [button assignments](docs/commands.md), [macro delays](docs/macros.md), [section writes](docs/section-writes.md), and [MXF findings](docs/file-format.md) for source addresses and limitations.

The original [B&K SR10.1 Editor 1.12.296 archive](https://files.remotecentral.com/view/6942-18483-1/sr101_editor.html) was unpacked statically, without executing the installer. Its original executable/DLLs and code database are not dependencies of this application. Proprietary installers, executables, databases, third-party configuration files, and personal remote backups are not distributed in this repository.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development and hardware-test guidance. Reports from other remote revisions are welcome; distinguish simulated results from physical tests.

## License

[The Unlicense](LICENSE): use, modify, sell, and redistribute this implementation freely, with no attribution requirement. Third-party dependencies and original vendor software retain their own licenses. This is an independent project, unaffiliated with B&K or Universal Remote Control.
