# SR10.1 serial protocol evidence

Evidence is static x86 disassembly of the B&K SR10.1 editor 1.12.296 installer, obtained October 25, 2026. The native reader implements the observed wakeup and memory-read path; the experimental writer uses only recovered, allowlisted configuration sections (see [section writes](section-writes.md)). Simulated tests validate implementation against these recovered vectors. Hardware verification on October 25, 2026 used the user’s SR10.1 and FT232R adapter at 115200 8N1. Wakeup, an 8192-byte system-section read, and the full 16-request, 471040-byte configuration read passed checksum validation. A subsequent same-content system-section write received both `55` acknowledgements and the expected device checksum; a fresh full 471040-byte read then matched the original configuration byte for byte. This verifies that round trip on this remote/cable. Physically changed LCD labels have not yet been tested, and raw-memory-to-MXF conversion remains incomplete.

## Binary provenance

- Installer SHA256: `cd76bf32d9c8bc7e79a048cd1a5f8adf38bfda09198398e5c3cc54e2c21452a3`
- JCOM.dll SHA256: `3e61affb42b408c973318955e3d36a89d2dbd82d5f64529bd7026ca99bc579ec`
- MXM07M.dll SHA256: `ecd22ae5d33733a402bbbb0c2814f6e235e3f687b5708498bce41908b7dc397f`
- Both DLLs have preferred image base `0x10000000`; addresses below are preferred virtual addresses, not file offsets.
- The InstallShield wrapper was extracted statically with filename-keyed nibble rotation/XOR, following the [open-source Unpacker implementation](https://github.com/pawstas80/Unpacker/blob/master/Unpacker/InstallShield.cs). Its extracted MSI and embedded MSZip cabinet were unpacked with 7-Zip. No installer execution was necessary.

## Serial settings

JCOM `LSerialPort::w_StartupInit` at `0x100129c0` initializes 9600 baud, 8 data bits, parity 0, stop-bit enum 0, and flow-control flags 0. The exact assignments are at `0x10012a08` (`c7410c80250000`), `0x10012a12` (`c6421008`), `0x10012a19`, `0x10012a25`, and `0x10012a2b`.

**The editor overrides that generic default to 115200.** MXM07M `TCommunicator::OnCreate` at `0x1000f230` calls `SetConnection(1,1)` via `6a01 6a01` at `0x1000f253`. `SetConnection` at `0x1000c0a0` chooses `0x2580` (9600) for flag 0, or `0x2580+0x19c80=0x1c200` (115200) for flag 1.

JCOM `w_SetupConnection` at `0x10012090` writes the DCB: 8N1, binary mode, no parity checking, no hardware/software flow control for the initialized flags; DTR and RTS control fields are set enabled. This is software behavior, not a verified requirement of the user's cable. Some unrelated DCB flags are inherited through GetCommState. MX700/MX800 target selection at MXM07M `0x1000f6f0` disables the separate keypad speed negotiation branch. The `(FFF01)` 9600-to-115200 negotiation in `wm_SetCommSpeedHigh` is not used by this reader.

## Wakeup

MXM07M `wp_WakeupEx`, `0x1000d6a0`:

1. Clear pending receive data.
2. Send byte `AA` (`68aa000000` at `0x1000d70a`, SendByte thunk call `0x1000d715`).
3. Wait for one byte, normally 1 second; an editor state flag can select 3 seconds. The reader currently uses 1 second.
4. Response `AA` succeeds. `A5` or `E1` delays 100 ms and retries. First `EB` records special mode, delays 100 ms and retries; a second `EB` succeeds. Other nonempty responses fail. Timeout delays 100 ms and retries.
5. At most two iterations.

The response table at `0x1000d8e8` maps `AA` to `0x1000d772`, `A5` to `0x1000d7c6`, `E1` to `0x1000d7b1`, and `EB` to `0x1000d77c`. A keypad-specific recovery branch is intentionally omitted.

## Read blocks from remote to PC

MXM07M `c_LimitedProgramLoadToPC`, `0x1000c630`, takes start address, inclusive final block address, and destination buffer. It wakes the remote, converts each address to an 8-bit 4 KiB block number, then sends:

```
04 START_BLOCK END_BLOCK START_BLOCK END_BLOCK
```

`wp_SendCommand` at `0x1000e880` sends the five arguments in order using five SendByte calls (`0x1000e90b`, `0x1000e91a`, `0x1000e929`, `0x1000e938`, `0x1000e947`). No extra framing byte is inserted there.

Address conversion at `0x1001b000` computes `(address >> 12) & 0xff`. Native validation deliberately rejects unaligned/out-of-range/reversed addresses instead of silently truncating. Payload length is `(END_BLOCK - START_BLOCK + 1) * 4096`, computed at `0x1000c6a7..0x1000c6bd`.

A directly observed caller, `TCommManager::SectionUploadSystemData` at `0x1000bda0`, requests `0xA000..0xB000`. Its wire command is `04 0A 0B 0A 0B` and its payload is 8192 bytes. **That section is not asserted to be a complete remote backup.** The full-upload call at `0x10005e20` uses the section plan below. The separate read at `0x1000679c` belongs to download preparation and is not part of this upload plan.

`wp_ReceiveData` at `0x1000edf0` receives raw bytes, with an initial 300 ms receive timer (`682c010000` at `0x1000ee31`) reset to 200 ms after progress (`68c8000000` at `0x1000eecd`). The reader mirrors these as inactivity deadlines and requires the complete payload.

The payload is followed by two checksum bytes, high byte first:

```
checksum = (0x0852 + sum(unsigned_payload_bytes)) & 0xffff
```

Checksum helper `0x1001afa0` initializes with `0x0852` at `0x1001afa6`, sums unsigned bytes at `0x1001afcd`, and stores high then low byte at `0x1001afe7` / `0x1001aff4`. `c_LimitedProgramLoadToPC` verifies those bytes via `wp_WaitAnswer2b` at `0x1000c740`, then delays 200 ms. The two-byte checker at `0x1000ec80` verifies in argument order, one-second byte waits.

Vectors: 8192 zero bytes yield `08 52`; `bytes(range(256))*32` yields `F8 52`. A wrong checksum or truncated payload is an error, never a successful backup. No host acknowledgement or write-to-memory command appears in this recovered read routine.

## Native implementation boundary

`protocol.py` exposes `RemoteReader.read_blocks(start_address,end_block_address)`, returning validated raw memory bytes. A supplied transport implements `write(bytes)->count`, `read(count,timeout)->bytes`, and `reset_input_buffer()`. It does not open ports itself. The reader exposes no erase, firmware update, or download-to-remote command. Physical serial activity is a deliberate caller action. The fixed-section writer is separate from the reader; neither API supports firmware updates or arbitrary erase operations. `sync.apply_label_changes` restricts edits to decoded five-byte LCD slots, compares a fresh system-section read with the source backup before writing, and requires exact section readback afterward.

`tests/test_protocol.py` covers the known section command, additive checksum, fragmented payload, truncated payload, bad checksum, wakeup responses, and pre-I/O bounds checks using a fake transport. These tests are simulated, not device tests.

## Cable documentation

The [original URC programming manual](https://fccid.io/OZ5URCMX200/Operational-Description/Operational-Description-per-CRN-23325-259569.pdf), printed page 1, specifies DB9 pin 3 (host TX) to 3.5 mm tip, pin 2 (host RX) to middle ring, pin 5 (ground) to base ring. That historical wiring description does not verify the current repaired cable or adapter configuration.

## Complete configuration upload plan

The upload dialog constructor sets mode field `+0x74=0` at `0x10004647`. Dispatch case 1 tests it at `0x1000563f` and calls upload-plan builder `0x10007250` (download uses `0x10006340`). The plan builder adds these task records via `0x10006170`, whose stores at `0x10006192..0x100061a8` establish internal command ID, start address and inclusive byte-end. IDs 6–9 are **internal dispatch IDs, not serial commands**.

| Internal ID | Start | Inclusive byte-end | Bytes | Plan call |
| --- | --- | --- | --- | --- |
| 6 | `0x9000` | `0xFFFF` | `0x7000` | `0x100072cb` |
| 7 | `0x10000` | `0x27FFF` | `0x18000` | `0x10007307` |
| 8 | `0x28000` | `0x51FFF` | `0x2A000` | `0x10007355` |
| 9 | `0x52000` | `0x7BFFF` | `0x2A000` | `0x100073a3` |

All four use generic uploader `0x10005cb0`, which chunks at `0x8000` bytes (`c745e000800000` at `0x10005d02`) and computes final block address as start + length − `0x1000` (`0x10005d66`). Its call at `0x10005e20` invokes the same checked wire command `04`. It retries each chunk up to twice. `full_read_plan()` exposes the exact 16 requests. Concatenated successful payloads span `0x9000..0x7BFFF`, exactly `0x73000` / 471040 bytes. This is the editor’s configuration upload region, not a whole-flash or firmware image. The first output byte corresponds to remote address `0x9000`.

After upload, the switch at `0x10005e75` stores sections 6/7/8/9 into dialog pointers `+0xCC/+0xD0/+0xD4/+0xD8`. Conversion routine `0x10007560` feeds `+0xCC` into `UM_Manager::FromBufferMapToSystem`, `+0xD0` into `0x10017dc0`, `+0xD4/+0xD8` into `0x100144d0`, then calls `UM_Manager::AsMXFileObject` at `0x10007626`.

`FromBufferMapToSystem` at `0x100119b0` consumes four successive system areas: `0x9000..0x9FFF` (0x1000 bytes, loader `0x100153a0`, manager member +0x6C), `0xA000..0xBFFF` (0x2000, `0x10018a00`, +0x70), `0xC000..0xEFFF` (0x3000, `0x100139a0`, +0x74), `0xF000..0xFFFF` (0x1000, `0x10016610`, +0x78). This is direct evidence that the `0x9000` section participates in configuration conversion.

`AsMXFileObject` at `0x10011190` calls a series of structured object converters; raw bytes are not simply an MXF file with a missing header. Exact semantics of those fields, learned IR and macros require further decoding and verification. Saving a raw backup must preserve its base address and format identity rather than naming it `.mxf`.

## System-section write path: recovered and same-content hardware round trip verified

`SectionDownloadSystemData` at `0x1000bd60` obtains manager member `+0x70`'s buffer via `0x10019270`, then explicitly passes `0xA000`, `0xB000`, buffer to `c_LimitedProgramDownload` (`0x1000bd88`). This establishes that the original editor has an isolated 8192-byte system-section write API.

`c_LimitedProgramDownload` at `0x1000c440` calls `c_LimitedProgramLoadToRCExt` at `0x1000c520`. The latter performs speed handling and wakeup, converts addresses to 4 KiB blocks, and sends:

```
03 START_BLOCK END_BLOCK START_BLOCK END_BLOCK
```

The opcode is `6a03` at `0x1000c596`, with the SendCommand call at `0x1000c59b`. For the original system-section call this is `03 0A 0B 0A 0B`.

1. Wait for device byte `55` (`0x1000c5cb`). Normal timeout 3 seconds, or 5 seconds if communicator field `+0x80` is nonzero; `wp_GetWaitTimeLong` at `0x1000d5f0` computes this.
2. Send exactly the raw payload via `wp_SendData` at `0x1000c5e3`. It queues up to 1500-byte pieces when the transmit queue is below 1500 bytes, yields the UI and sleeps 2 ms (`0x1000ed20`).
3. Wait for output queue completion with a 30-second timeout (`0x1000c5e8` / `0x1000c5ed`; imported `LTimer::StartTimerSec` at `0x1001c1ea`).
4. Receive the two checksum bytes from the device, high then low, matching `(0x0852 + sum(payload)) & 0xffff` (`0x1000c60e`). Timeout passed to each checker is long-wait + 1, thus 4 or 6 seconds. **The host does not append checksum bytes to this write payload.**
5. The program-download wrapper waits for one final `55` at `0x1000c496` (normal 5 seconds) or `0x1000c47b` (flagged 6 seconds). It then delays 100 ms and clears RX at `0x1000c4a6..0x1000c4ae`.

The distinct data-download wrapper at `0x1000c4c0` uses a final 4-second `55` wait, so these wrappers should not be conflated. Timeout or mismatching response returns failure. No explicit erase command, rollback, verify-read or restoration appears in the isolated system-section wrapper. `RemoteWriter.write_system_section(bytes)` now implements this fixed 8192-byte path. It validates the immutable payload length and bounded drain capability before I/O, uses normal-mode timing, and performs no automatic retry or rollback. Its six simulated state-machine tests cover success, pre-I/O validation, ready failure, checksum failure, final-ack failure, and output-drain failure. The coordinating agent subsequently ran this native writer against the physical remote using identical original system bytes. Ready acknowledgement, device checksum, and final acknowledgement passed. It then reread all 16 configuration chunks and verified every one of the 471040 bytes against the original backup. This is same-content write verification; it does not establish physical changed-label behavior, general MXF programming, macro editing, or learned-IR editing.

The PC-side bounded API strongly suggests that normal firmware supports replacing the requested range, but it does not prove the MCU's internal erase granularity, atomicity, neighboring-region preservation during failure, or power-loss recovery. Those points cannot be asserted from this desktop routine alone. A checksum from the remote confirms transmitted content according to the editor protocol; the successful same-content hardware test additionally supplied independent full-region readback. That successful run does not establish behavior during interruption or failure.

## Internal system checksum is separate from the serial checksum

The first two bytes of the 8192-byte system section are a **big-endian checksum, not a fixed signature**. The system serializer at `0x100189b0` invokes `0x1001b4d0`, which stores `(0x0852 + sum(section[2:])) & 0xffff` into those two bytes. The original captured section starts `8F 91` because its remaining bytes sum to `0x873F` modulo 65536. A label edit changes this internal checksum, and the staged document must recompute it.

This stored checksum covers only section bytes 2 onward. The serial transport checksum instead covers the complete transmitted payload, including the stored checksum bytes. For example, an otherwise zero 8192-byte section has internal checksum `08 52` and transport checksum `08 AC`. These fields are not interchangeable.

`RemoteWriter` rejects an invalid internal checksum before any serial I/O. `apply_label_changes` validates original and edited documents before I/O and permits only exposed LCD label bytes plus the two correctly derived internal-checksum bytes. At least one actual label byte must differ. This keeps required checksum repair from being mistaken for an unsupported arbitrary memory edit.
