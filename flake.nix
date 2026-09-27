{
  description = "ThinkPad T480 EC accelerometer and calibrated Sway rotation";
  inputs.nixpkgs.url = "https://channels.nixos.org/nixos-unstable/nixexprs.tar.zst";
  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};
      python = pkgs.python3.withPackages (ps: [ ps.evdev ]);
      driver = pkgs.callPackage ./package.nix { kernel = pkgs.linuxPackages_latest.kernel; };
      rotate = pkgs.callPackage ./rotate-package.nix {};
      moduleTest = nixpkgs.lib.nixosSystem {
        inherit system;
        modules = [ self.nixosModules.default ({ ... }: {
          system.stateVersion = "26.05";
          boot.kernelPackages = pkgs.linuxPackages_latest;
          hardware.t480EcAccel = { enable = true; probeOnly = false; autoRotate = true; };
        }) ];
      };
    in {
      nixosModules.default = import ./module.nix;
      packages.${system} = { default = rotate; t480-rotate = rotate; t480-ec-accel = driver; };
      apps.${system}.default = { type = "app"; program = "${rotate}/bin/t480-rotate"; };
      checks.${system} = {
        kernel-module = driver;
        tool = rotate;
        rotation = pkgs.runCommand "t480-rotation-tests" { nativeBuildInputs = [ python pkgs.stdenv.cc ]; } ''
          cp ${./rotate.py} rotate.py
          cp ${./test_rotate.py} test_rotate.py
          cp ${./test_mailbox.py} test_mailbox.py
          cp ${./t480_ec_accel.c} t480_ec_accel.c
          python3 -m unittest discover -p 'test_*.py'
          touch $out
        '';
        nixos-module = moduleTest.config.systemd.user.units."t480-auto-rotate.service".unit;
      };
      devShells.${system}.default = pkgs.mkShell {
        packages = [ python pkgs.sway ];
      };
    };
}
