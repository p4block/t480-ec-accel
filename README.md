# thinkpad-rotate

A small Rust program that rotates a Sway desktop from a ThinkPad base
accelerometer. One thread, direct evdev and Sway IPC, no polling timer or
interpreter. Hardware access is provided separately by
[thinkpad-ec](https://github.com/p4block/thinkpad-ec), currently supporting tested
X230 and T480 firmware.

## NixOS

Import `module.nix` or the flake's `nixosModules.default` and enable:

```nix
services.thinkpadRotate.enable = true;
```

Enable `hardware.thinkpadEc.accelerometer` in the driver module separately.
Ensure Sway includes `include /etc/sway/config.d/*` for session integration.
The user service starts with Sway only once `~/.config/thinkpad-rotate.json`
exists. Set `services.thinkpadRotate.autoStart = false` for manual startup.

## Calibrate and run

```sh
systemctl --user stop thinkpad-rotate
thinkpad-rotate sample                   # Ctrl-C to stop
thinkpad-rotate calibrate
systemctl --user start thinkpad-rotate
# Or: thinkpad-rotate run --dry-run
```

The sensor is in the **base, not the lid**. Keep the base near vertical for all
four calibration poses. At each prompt hold the displayed desktop upright,
press Enter, then hold still for several seconds. Calibration restores the
previous display transform, including on cancellation.

Rotation requires one second in a calibrated pose. Ambiguous or flat poses
retain the current transform. A stopped/disconnected sensor stops the program;
it does not repeatedly reopen the device. Ctrl-C, SIGTERM and errors close
acquisition and attempt to restore the original display transform.

Defaults: `/dev/input/thinkpad-ec-accel`, the sole active eDP/LVDS display,
`$XDG_CONFIG_HOME/thinkpad-rotate.json` (normally `~/.config/thinkpad-rotate.json`).
Use `--device`, `--output`, or `--profile` to override; `--calibration` is an
alias for `--profile`. `sample` works without Sway. Calibration is required;
there is no assumed machine-specific profile.

## Migration

Stop `t480-auto-rotate` before enabling this service. The former Python tool's
four-pose JSON works unchanged: copy your `~/.config/t480-auto-rotate.json` to
`~/.config/thinkpad-rotate.json`. Explicit legacy X230 profiles containing
`center`, `positive` and `negative` pairs also work. Legacy profiles retain
their flat-to-normal behavior. Recalibrate if you used the old built-in X230
profile without a file.

## Build

```sh
cargo test
cargo build --release
# Or:
nix build
nix flake check
nix run . -- --help
```

Tested on Linux x86_64. No other compositor support is claimed. [WTFPL](LICENSE).
