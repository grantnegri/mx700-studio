# Existing macro delays

`macros.py` decodes existing device macro records in a complete SR10.1 configuration backup. It stages changes to existing delays, inserts delays between steps, and removes delays. It never opens a serial port. A staged change is a complete binary copy, preserving other configuration sections. This does not create new macros or establish physical write support for macro banks.

For example, `28 C5 28 C5 28` transmits command `0x28` three times with two 0.5-second pauses. Command names come from the corresponding configured device/button.

## Binary evidence

Addresses are preferred virtual addresses in the recovered editor 1.12.296 DLLs. The macro bank begins at remote 0x28000 (full backup offset 0x1F000). It contains 21 successive 8192-byte device banks; slot20 represents MAIN. Each bank has a two-byte big-endian checksum `(0x0852 + sum(bank[2:])) & 0xFFFF`, a bank identity byte `0x28 + 2*slot`, then43 fixed190-byte records. Remaining bytes are preserved.

- MXM07M `0x100144d0`: reads21 banks of0x2000 bytes.
- `0x10014b80`: serializes each bank and calls checksum routine `0x1001b4d0`.
- `0x10014c00`: builds device macro banks and stores identity byte at `0x10014ca8`.
- `0x10014ec0`: loops43 records; writes at bank+3+record*190; clears each record toFF before encoding.
- `0x100150e0`, `0x1001b0d0`, `0x1001b030`: resolve triggers. Records0/1 are Power On/Off,2..41 are the40 LCD buttons,42 is device-entry macro. Raw command key IDs are resolved through UDJF `TKeyRegMX07::GetButtonMapIDMX7KeyID`.
- `0x1001b930`: encodes steps; `0x1001bc90`: decodes them.

A record beginning FF FF is empty. Otherwise an initial FF is a before-macro flag; a non-FF first byte is an action macro. The distinction is preserved without changing assignment flags elsewhere. Subsequent FF ends the stream. Values below80 hex are command key IDs. 80..9F select a device context, A0..BF jump to a page, C0..FD encode pauses in the low6 bits. The serializer divides pauses into chunks of at most61 units (`0x1001bb8e..0x1001bbde`); the decoder merges a following pause token after a61-unit chunk (`0x1001be54..0x1001beb3`). FE is not emitted by this encoder and is rejected. Unsupported command/device/page values are rejected instead of guessed.

Each pause unit is0.1 seconds. This is directly established in MXM07G's delay dialog: `0x10032323` loads integer delay member+C8, `0x10032329` divides by double10.0 at `0x1004e158`, and `0x1003263d` multiplies the entered seconds by that same10.0. The bundled B&K SR10.1 Programming Manual, printed page32, supports delays from0.1 to30 seconds. The native editor uses that range. **A delay placed first makes the macro require holding the trigger for that duration**, as described on printed pages13,27 and44; it is not merely an unconditional startup wait.

## Preservation and validation

Edits require a complete471040-byte backup, matching bank identity and checksum, a supported terminated stream, and a whollyFF unused tail in the modified record. They retain the original before/action mode, commands, context changes and page jumps. They may shift bytes only inside the same190-byte record and recompute only its bank checksum. At least oneFF terminator is retained, even though the original encoder has less conservative capacity handling.

`validate_delay_changes` verifies macro-only edits independently: both full backups must validate; other sections, bank metadata, unused bank tail, macro assignments, execution mode, and every non-delay token remain unchanged. It returns changed device slots for a coordinating transfer layer. It is not a hardware transfer function.

Tests cover raw command/delay decoding, before-macro context, fixed-length edits, checksum correction, delay chunk boundaries, insertion/removal, input guards, opaque-tail/capacity rejection, and immutable round trips against the captured backup. These are offline tests. No physically changed macro has been transmitted or timed on this remote.
