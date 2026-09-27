{ lib, stdenv, kernel }:
stdenv.mkDerivation {
  pname = "t480-ec-accel";
  version = "0.1";
  src = lib.cleanSourceWith {
    src = ./.;
    filter = path: type: type == "directory" || builtins.elem (baseNameOf path) [ "Makefile" "t480_ec_accel.c" ];
  };
  dontPatchELF = true;
  nativeBuildInputs = kernel.moduleBuildDependencies;
  hardeningDisable = [ "pic" ];
  makeFlags = [
    "-C" "${kernel.dev}/lib/modules/${kernel.modDirVersion}/build"
    "M=$(PWD)"
  ];
  buildFlags = [ "modules" ];
  installPhase = ''
    install -Dm644 t480_ec_accel.ko $out/lib/modules/${kernel.modDirVersion}/extra/t480_ec_accel.ko
  '';
  meta.description = "ThinkPad T480 N24HT37W EC accelerometer";
}
