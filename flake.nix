{
  description = "Calibrated ThinkPad accelerometer rotation for Sway";
  inputs.nixpkgs.url = "https://channels.nixos.org/nixos-unstable/nixexprs.tar.zst";
  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};
      package = pkgs.callPackage ./default.nix {};
      machine = nixpkgs.lib.nixosSystem {
        inherit system;
        modules = [ self.nixosModules.default { system.stateVersion = "26.05"; services.thinkpadRotate.enable = true; } ];
      };
    in {
      packages.${system}.default = package;
      apps.${system}.default = { type = "app"; program = "${package}/bin/thinkpad-rotate"; };
      nixosModules.default = import ./module.nix;
      checks.${system} = { build = package; module = machine.config.systemd.user.units."thinkpad-rotate.service".unit; };
      devShells.${system}.default = pkgs.mkShell { packages = [ pkgs.cargo pkgs.rustc pkgs.rustfmt ]; };
    };
}
