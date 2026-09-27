# t480-ec-accel

Read the ThinkPad T480's base accelerometer through its embedded controller
and optionally rotate a Sway desktop. Includes an out-of-tree Linux input
driver, a NixOS module, and a calibration/rotation tool.

Tested on a **coreboot T480, EC N24HT37W, Linux 7.2.7**. No firmware flashing
or EC debug unlock is required. Adapted from an X230 G2HT35WW mailbox driver;
the T480 protocol was checked against N24HT37W before live testing.

## Supported setup

- ThinkPad T480 with EC firmware **N24HT37W**. Other revisions are rejected.
- Coreboot ACPI providing `\_SB.PCI0.LPCB.EC.ECLK` and the mailbox at
  I/O ports `0x1610/0x1611`. Stock Lenovo BIOS has not been tested.
- Linux input/evdev. The driver reports two raw axes and fresh-frame heartbeats.
- Sway for automatic rotation; other consumers can use the input device directly.

Acquisition, physical tilt response, shutdown on close, normal-user access,
and calibrated Sway rotation have been tested. Suspend/resume support is
implemented but has not been tested. Protocol evidence: [PROTOCOL.md](PROTOCOL.md).

## NixOS

Clone this repository into your configuration as `t480-ec-accel`, then import:

```nix
{
  imports = [ ./t480-ec-accel/module.nix ];
  hardware.t480EcAccel = {
    enable = true;
    probeOnly = false;
    autoRotate = true;
  };
}
```

For a first diagnostic test, set `probeOnly = true` and `autoRotate = false`.
That queries status without starting acquisition or registering an input device.
A successful idle response looks like `status=00 rate=200 filter=2 error=00`.

Flake users can add this repository as an input and import
`inputs.t480-ec-accel.nixosModules.default`. The module builds against your
configured `boot.kernelPackages.kernel`, including when it differs from the
kernel pinned by this repository's standalone package.

After rebuilding, reboot or reload the module to apply changed module options.
Stop any sensor consumers before reloading. The module name is `t480_ec_accel`.

| Option | Default | Purpose |
| --- | --- | --- |
| `hardware.t480EcAccel.enable` | `false` | Install and load the driver and tools |
| `hardware.t480EcAccel.probeOnly` | `true` | Status query only, no input device |
| `hardware.t480EcAccel.autoRotate` | `false` | Install the Sway user service |

Ensure your Sway config includes the NixOS session integration:

```sway
include /etc/sway/config.d/*
```

It exports `SWAYSOCK` and manages `sway-session.target`. Restart your Sway
session after adding it. The udev rule grants the active local session access
to this sensor; broad membership in the `input` group is unnecessary.

## Sampling and calibration

```sh
t480-rotate sample                  # Ctrl-C closes the sensor
systemctl --user stop t480-auto-rotate
t480-rotate calibrate
systemctl --user start t480-auto-rotate
```

The accelerometer is in the **base, not the lid**. Calibrate all four poses
with the base near vertical. At each prompt, hold the laptop so the displayed
desktop is upright, press Enter, and hold still for about four seconds.
Calibration restores the previous display transform afterward.

Calibration is stored in `~/.config/t480-auto-rotate.json` by default. The
NixOS service explicitly uses that path. It starts with future Sway sessions
once that file exists. The CLI also supports `--output` and `--calibration`.

The service rotates only the active internal eDP output. It requires a pose
to remain stable for 1.5 seconds, ignores poses outside the calibrated
neighborhoods, and stops if fresh heartbeats cease for three seconds.
**Flat or on-stand positions do not necessarily restore normal orientation**;
outside the calibrated poses, the last transform is retained. A separate
resting pose is not currently supported.

```sh
systemctl --user stop t480-auto-rotate
swaymsg output eDP-1 transform normal
```

Acquisition starts on the first input open and stops on the last close.
No sensor readings are collected merely because the module is loaded.

## Standalone builds

```sh
nix build .#t480-ec-accel             # kernel module for pinned latest kernel
nix run . -- sample                  # Sway/evdev tool; driver must be installed
nix flake check                      # driver build, module evaluation, Python tests
```

Without Nix, build the driver with matching kernel development headers:

```sh
make -C /lib/modules/$(uname -r)/build M="$PWD" modules
sudo insmod ./t480_ec_accel.ko probe_only=1
```

Python tooling needs Python 3, `evdev`, and `swaymsg`; run `python3 rotate.py`.
Automatic installation, udev permissions, and systemd integration currently
ship through NixOS only; no DKMS packaging is provided.

## Troubleshooting

```sh
journalctl -k -g t480_ec_accel
cat /sys/module/t480_ec_accel/parameters/{active,last_error,samples}
journalctl --user -u t480-auto-rotate
```

`active` means acquisition started successfully, not a physical rail measurement.
Firmware mismatch returns `ENODEV`; a missing ACPI mutex or busy mailbox also
prevents operation. The status probe writes mailbox arguments and acknowledges
responses, although it never enables sampling. Other raw EC tools that ignore
ECLK can interfere; the driver does not override their ownership.

## Repository layout

- `t480_ec_accel.c`, `Makefile`: firmware-restricted kernel driver.
- `rotate.py`, `test_rotate.py`: user-space tool and tests.
- `module.nix`, `package.nix`, `rotate-package.nix`, `flake.nix`: Nix packaging.
- `PROTOCOL.md`: firmware provenance, command traces, and validation evidence.

No vendor firmware, machine dumps, calibration data, or personal NixOS
configuration is included. The original driver's WTFPL SPDX notice is retained;
see [LICENSE](LICENSE). Its kernel `MODULE_LICENSE("GPL")` declaration is also
retained from the supplied source.
