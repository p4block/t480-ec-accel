{ config, lib, pkgs, ... }:
let
  cfg = config.services.thinkpadRotate;
  package = pkgs.callPackage ./default.nix {};
in {
  options.services.thinkpadRotate = {
    enable = lib.mkEnableOption "calibrated ThinkPad Sway rotation";
    autoStart = lib.mkOption { type = lib.types.bool; default = true; description = "Start with the Sway session once calibrated."; };
  };
  config = lib.mkIf cfg.enable {
    environment.systemPackages = [ package ];
    systemd.user.services.thinkpad-rotate = {
      description = "Calibrated ThinkPad desktop rotation";
      wantedBy = lib.optional cfg.autoStart "sway-session.target";
      partOf = [ "sway-session.target" ];
      after = [ "sway-session.target" ];
      unitConfig.ConditionPathExists = "%h/.config/thinkpad-rotate.json";
      serviceConfig = {
        ExecStart = "${package}/bin/thinkpad-rotate run --profile %h/.config/thinkpad-rotate.json";
        Restart = "no";
        TimeoutStopSec = 15;
        NoNewPrivileges = true;
        ProtectSystem = "strict";
        ProtectHome = "read-only";
        ReadWritePaths = [ "%t" ];
        RestrictAddressFamilies = [ "AF_UNIX" ];
      };
    };
  };
}
