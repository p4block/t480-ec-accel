{ pkgs, python3, writeShellApplication }:
let python = python3.withPackages (ps: [ ps.evdev ]);
in writeShellApplication {
  name = "t480-rotate";
  runtimeInputs = [ python pkgs.sway ];
  text = ''exec ${python}/bin/python3 ${./rotate.py} "$@"'';
}
