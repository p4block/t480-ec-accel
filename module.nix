{ config, lib, pkgs, ... }:
let
  cfg = config.hardware.t480EcAccel;
  driver = pkgs.callPackage ./package.nix { kernel = config.boot.kernelPackages.kernel; };
  rotate = pkgs.callPackage ./rotate-package.nix {};
in {
  options.hardware.t480EcAccel = {
    enable = lib.mkEnableOption "T480 N24HT37W EC accelerometer";
    probeOnly = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Query status at module load without registering or powering the sensor.";
    };
    autoRotate = lib.mkEnableOption "calibrated Sway rotation service";
  };
  config = lib.mkIf cfg.enable {
    boot.extraModulePackages = [ driver ];
    boot.kernelModules = [ "t480_ec_accel" ];
    boot.extraModprobeConfig = ''
      options t480_ec_accel probe_only=${if cfg.probeOnly then "1" else "0"}
    '';
    environment.systemPackages = [ rotate ];
    # Give the active local session access to this accelerometer only.
    services.udev.packages = [ (pkgs.writeTextFile {
      name = "t480-ec-accel-udev";
      destination = "/lib/udev/rules.d/70-t480-ec-accel.rules";
      text = ''
        SUBSYSTEM=="input", KERNEL=="event*", ATTRS{name}=="ThinkPad T480 EC accelerometer", TAG+="uaccess", ENV{LIBINPUT_IGNORE_DEVICE}="1"
      '';
    }) ];
    systemd.user.services.t480-auto-rotate = lib.mkIf cfg.autoRotate {
      description = "Rotate Sway from the ThinkPad base accelerometer";
      wantedBy = [ "sway-session.target" ];
      partOf = [ "sway-session.target" ];
      after = [ "sway-session.target" ];
      unitConfig.ConditionPathExists = "%h/.config/t480-auto-rotate.json";
      serviceConfig = {
        ExecStart = "${rotate}/bin/t480-rotate run --calibration %h/.config/t480-auto-rotate.json";
        # A stale/erroring sensor stops rotation; no infinite reopen loop.
        Restart = "no";
        NoNewPrivileges = true;
        ProtectSystem = "strict";
        ProtectHome = "read-only";
      };
    };
  };
}
