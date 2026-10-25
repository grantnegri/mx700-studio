# Restricted configuration writes

Static evidence: MXM07M.dll from editor 1.12.296, SHA256 `ecd22ae5d33733a402bbbb0c2814f6e235e3f687b5708498bce41908b7dc397f`. Addresses below are preferred virtual addresses. These additional write paths have simulated coverage, **not physical hardware verification**. The prior same-content A000–BFFF write remains the only physical write test.

## Original download plan and checksums

The full-download builder at `0x10006340` copies these buffers into one system payload:

| Remote region | Manager member | Getter | Copy call | Internal checksum |
| --- | --- | --- | --- | --- |
| 9000–9FFF | +6C | 100154D0 | 10006839 | first two bytes over remaining 4094 bytes |
| A000–BFFF | +70 | 10019270 | 1000686A | first two bytes over remaining 8190 bytes |
| C000–EFFF | +74 | 10013CD0 | 1000689B | first two bytes over remaining 12286 bytes |
| F000–FFFF | +78 | 10016A20 | 100068FC | first two bytes over remaining 4094 bytes |

The builder creates internal task ID5 for 9000–E000 inclusive block starts at `0x100068D7`, or 9000–F000 at `0x10006932`. This is a system-region download and not a firmware write. The task dispatcher at `0x1000588F` selects `c_LimitedDataDownload` only for internal ID4; other tasks in this branch (including ID5) invoke `c_LimitedProgramDownload` at `0x100058DA`.

The independent exported `SectionDownloadSystemData` provides the known A000–BFFF path. There is no corresponding exported isolated shortcut or C000 wrapper found. Applying the generic program writer to a narrower complete checksum section follows its explicit start/end-address mechanism; it has not been physically validated for those regions. C000 and F000 are deliberately excluded from the native write API because no exposed feature currently needs them.

All internal checksums use helper `0x1001B4D0`: big-endian `(0x0852 + sum(section[2:])) & 0xFFFF`. Shortcut getter `0x100154D0` and serializer `0x10015360` both call it with size1000. C000 getter `0x10013CD0` and serializer `0x10013960` call it with size3000. Captured backup checksums validate for9000 (905A), A000 (8F91), C000 (16B5), and F000 (480F).

## Macro and learned banks use the data wrapper

Planner `0x10006E20` handles two bank families from manager members +80 and +84:

- First family base28000, 21 slots of2000 bytes: range28000–51FFF. Slot start arithmetic is at `0x10006F1A..0x10006F26`. Inclusive final block is `base + last_slot*2000 + 1000`, computed at `0x10006F2E..0x10006F37`. Task ID4 is queued at `0x10006F62..0x10006F67`.
- Second family base52000, 21 slots of2000 bytes: range52000–7BFFF. Equivalent address arithmetic is at `0x10007008..0x10007025`; task ID4 is queued at `0x10007050..0x10007055`.

The original planner can coalesce consecutive marked slots. Our API writes exactly one slot per call. Getter `0x10014CC0`, called for both families at `0x10006EA8` and `0x10006F96`, loops21 times and calls checksum helper `0x1001B4D0` with each slot buffer and size2000 at `0x10014CF3`. All42 slot checksums match the original hardware backup.

`c_LimitedDataDownload` at `0x1000C4C0` calls the same common `c_LimitedProgramLoadToRCExt` sender at `0x1000C4D8`. Therefore its command remains **03**, not internal task ID4. After the common exchange, it waits for final55 with **four seconds** at `0x1000C4EA..0x1000C4F6`, then delays100ms and clears RX. Program-download uses the previously recovered five-second normal final acknowledgement. Common exchange uses wakeupAA, `03 first last first last`, ready55 (3s normal), raw payload, bounded output drain, and the remote's two-byte transport checksum (4s normal). The host sends no checksum trailer.

## Native API boundary

`RemoteWriter.write_configuration_section(start, payload)` permits only:

- 9000, exactly1000 bytes, program wrapper.
- A000, exactly2000 bytes, program wrapper; existing `write_system_section` remains compatible.
- 28000 + slot*2000, slot0..20, exactly2000 bytes, data wrapper.
- 52000 + slot*2000, slot0..20, exactly2000 bytes, data wrapper.

The method validates immutable payload type, exact size, address allowlist, valid internal checksum, and bounded transport drain before serial activity. It rejects half slots, combined slots, unrelated configuration, and firmware. It never retries or rolls back automatically. Higher-level synchronization must validate which semantic edits are permitted, compare the original region with a fresh remote read, and read back changed sections. A successful transport checksum alone does not prove the remote's subsequent behavior or power-loss resilience.

`tests/test_section_writer.py` exercises all44 allowed regions, exact request/payload boundaries, wrapper-specific timeouts, invalid regions and checksums before I/O, and failure-without-retry behavior. Existing15 protocol tests preserve the previously implemented system writer exchange.
