{ lib, rustPlatform }:
rustPlatform.buildRustPackage {
  pname = "thinkpad-rotate";
  version = "0.1.0";
  src = lib.fileset.toSource {
    root = ./.;
    fileset = lib.fileset.unions [ ./Cargo.toml ./Cargo.lock ./src ];
  };
  cargoLock.lockFile = ./Cargo.lock;
  doCheck = true;
  meta = {
    description = "Opt-in Sway rotation from the ThinkPad EC accelerometer";
    license = lib.licenses.wtfpl;
    platforms = lib.platforms.linux;
    mainProgram = "thinkpad-rotate";
  };
}
