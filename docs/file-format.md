# MXF text format evidence

Verified against `9-3-02.mxf` (831813 bytes, MX Editor 1.04 sample) and installer `B_K_7.dat` (103701 bytes, version word 0x25 / model word 0x70). Native parser is `mx700_studio/mxf.py`.

UDJF.dll exported `MXDirText::TextWriteToDisk` RVA 0x5afc0 writes 12 header bytes followed by text length plus NUL. Disassembly at RVA 0x5b041..0x5b06e masks the uint16 field at offset 6 with 0x3ff. `TextReadFromDisk` RVA 0x5b360 reads the same layout; at RVA 0x5b48c..0x5b498, rejects lengths >=64. Text identifier is uint16LE offset4. Four bytes offset8..11 and high six bits of offset6..7 are retained as opaque.

`MXDirText::GetDeviceName` RVA0x5b200 requests identifier0x8001 then falls back to0x8002; `GetDeviceNameOnRc` RVA0x5b230 prefers0x8002 then0x8001.

Legacy record prefix 16 00 07, byte3 observed0/1; device table begins with8002,8001 then shared-ID page/title/button text records. MAIN table0xd348..0xdaaf has113 records, page IDs1,22,43 (Hard Buttons). TV table0x1404a..0x149f4 has155 records, titles at1,22,43,64,85. Physical paired labels inferred from repeated values and sequential IDs; no upload validation.

Modern record prefix16 00 70; byte3 includes uninitialized0xcd as well as0. Each page has local IDs and records need not be sorted. One contiguous table contains one page title (anywhere) and labels/alternate labels. Tables precede device-name table. Initial MAIN text table0x79e..0x99e includes title ID0x1f at0x98b; device name records0x1fff and0x2011. Native UI exposes individual text records, without inferring physical button assignment. 19 devices recovered: MAIN,FAV,TUNER,VIDEO,AUDIO,IN1..IN14. 2052 records total.

All edits use printable ASCII, pad to existing string length, never relocate bytes or alter headers; unchanged bytes are preserved exactly. Source overwrite and existing target overwrite refused. This does not establish hardware compatibility, whole-file integrity rules, macro meaning, IR semantics, or support for other version layouts. Development fixture checks confirmed byte-identical unchanged legacy decode, confined edits, reparse, validation guards, source protection, and modern template confined edit/reparse.
