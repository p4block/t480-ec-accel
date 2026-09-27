# T480 EC accelerometer investigation

2026-09-27. This is an adaptation of an X230 G2HT35WW driver.
The T480 code is restricted to model T480 / ThinkPad T480 and EC ID N24HT37W.
The MEC1653 hardware shares the historical coreboot h8 interface; the h8 name
alone was not used as evidence for mailbox compatibility.

## Firmware evidence

Source: https://download.lenovo.com/pccbbs/mobiles/n24ur39w.iso
Lenovo release history: https://download.lenovo.com/pccbbs/mobiles/n24ur39w.html
The ISO contains FLASH/N24ET77W/$0AN2400.FL2. Remove its 32-byte `_EC` header
for the EC address space (286720 bytes). SHA256 of that payload:
`befcb425b9f2a83b959c0ef3ee490420b7c5e5ffa2a792fda821d0ff355e77cf`.
Firmware ID at payload offset 0x240: N24HT37W.
Saved running-machine boot logs also report N24HT37W-3.36.

Disassembled with GNU binutils 2.46, ARC600 little endian. First wrap in an
ELF with a code section, otherwise objdump treats the raw binary as data:

```
objcopy -I binary -O elf32-littlearc -B ARC600 \
  --rename-section .data=.text,alloc,load,readonly,code,contents ec.bin ec.elf
objdump -d ec.elf
```

Addresses below refer to the stripped payload, not the update container.

- 0x2c488 sets up mailbox device 0, port 0x1610, enabled=1 via 0xfa64.
  Constant pool: 0x2c7f4 holds 0x1610; table 0x304d4 maps device 0 to
  register 0xff3364. Code 0xfb10 constructs `(port << 16) | 0x8000 | enable`,
  therefore BAR value 0x16108001, matching the X230 mailbox mapping.
- 0x2c5dc dispatches the command byte in EC MMIO 0xff0100. It reads the
  argument at +0x10 and clears +0x14 through +0x2c.
- Jump table 0x2c998 maps command 0x10 to 0x2c9ae, 0x11 to 0x2c9e2,
  0x14 to 0x2cb02, and 0x17 to 0x2cb34.
- 0x10 calls 0x1d654: low 16 bits select rate, byte 2 selects the averaging
  count (clamped 1..8). Nonzero rate requests sampling; zero requests stop.
  The existing 0x0a0200c8 argument gives 200 Hz and averaging count 2.
- 0x11 calls 0x1d62c -> 0x1d39c with max 5 records. Its handler constructs
  the response without consuming payload arguments. Records are X/Y little
  endian 16-bit values plus a byte per record (stride 5). Code 0x1d592 adds
  an offset of 512 after axis mapping/scaling. This is the legacy two-axis
  output path, even though firmware also has a three-axis path (0x19).
- 0x14 takes boolean argument 0/1 and calls 0x1d728, which requests sensor
  power state through task 0x1b. Check the full result word at reply +28.
- 0x17/0x82 calls 0x1d770: status bit 0 is active sampling, bit 1 pending
  start, bit 3 self-test/pending self-test; subsequent bytes expose rate and
  filter. Status errors occupy reply byte 31.
- Completion 0x2cfd0 writes 0xff to the EC command register, then the command
  echo to MMIO +4. Host-side completion/ack follows the supplied X230 code;
  confirmed by successful live status and sampling transactions.

## Coreboot path

The current board's LPC decode includes 0x1600..0x167f. ACPI has ECLK and a
TWRI reservation for 0x1610..0x161f. Claiming just 0x1610..0x1611 avoids EC3
at 0x1618. No EC debug unlock, GPIO change, or firmware flash is needed.
The other `ECGS` reservation (0x1602/0x1606) is not this mailbox.

## Validation status

Kernel module builds against the installed NixOS kernel 7.2.7.
Live status query succeeded: status=00, rate=200, filter=2, error=00.
An 8-second read delivered 15 frames near X=515, Y=513. A second 30-second
read delivered 58 frames while the owner tilted left/right and forward/back
twice, then put the laptop on the desk. X ranged 306..722 and Y 310..729;
values returned near 512 when flat. Both closes reported active=N, last_error=0.
The two tests accumulated 73 samples.
The default `probe_only=1` mode only queries 0x17/0x82 and registers no input
sensor. It still performs a mailbox transaction, including argument/index
writes and acknowledgement; it is not electrically read-only.

Acquisition, physical axis response, and close/shutdown are verified.
The owner subsequently confirmed calibrated Sway rotation works with all four
poses calibrated near vertical. Suspend/resume remains unverified. Stock Lenovo
BIOS is untested and may lack the required ACPI ECLK mutex. Do not widen the
firmware guard based on shared EC family alone. The calibration tool requires physical poses before rotation.
