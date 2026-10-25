# SR10.1 LCD memory support

The native application can inspect an 8192-byte system-section read or a 471040-byte configuration backup spanning remote addresses 0x9000–0x7bfff. In a full backup, the system section is at file offsets 0x1000–0x2fff.

The current decoder checks the internal system checksum and supported page-count bounds. Bytes 0–1 contain a big-endian checksum, not a fixed signature; other header bytes are preserved. It displays MAIN and active devices with their LCD pages in physical row order. Each label occupies exactly five bytes. Edits accept at most five printable ASCII characters, preserve left/right alignment and change only the selected slot and the two checksum bytes. Saving creates a new binary copy and refuses to replace the original or an existing file. Staging and saving do not send anything to the remote.

This is a partial configuration decoder. Hard-button commands, macros, learned IR and other memory regions remain untouched and are not represented as editable objects. It does not reconstruct an MXF document. Device names edited through MAIN labels are reflected in the parsed device names.

## Evidence

Static analysis of the recovered editor's MXM07M.dll supplies these offsets:

| Field | Offset within system section | Evidence RVA |
|---|---:|---:|
| MAIN title |0x97|0x19460|
| Device presence/setup words |3+2×slot|0x185a0,0x19510|
| Device page counts |0x800+slot|0x196c0|
| LCD pages |0x815+200×slot+50×page|0x19770|
| MAIN device-name pages |0x17b5+50×page|0x19510,0x19770|
| Five-character column extraction |row×10 plus 0(left) or 5(right)|0x1ae10|

The original editor's logical slots 0–4 address the right column; 5–9 address the left. The native display converts these to physical rows. MXM07M serializer RVA 0x189b0 calls checksum routine 0x1b4d0. The routine starts at 0x0852, adds every byte from offset 2 through the end of the section, keeps the low 16 bits and stores the result big-endian at offsets 0–1. The physical backup validates exactly: 0x873f + 0x0852 = 0x8f91. Label edits recompute this internal checksum; transfer checksums are a separate mechanism.

All offsets above are section-relative; staged edits in a full backup account for the 0x1000-byte prefix.

The verified physical backup recovered MAIN, HDMI (two pages), KAICO (one), B&K (three) and BENQ (one). Tests check original preservation, exact fixed-slot edits, alignment, blank labels, capacity/ASCII guards, reparse, save-copy behavior and unchanged data outside the system section. The private backup is not bundled with the application; its optional integration test runs when present beside the application folder.
