{
  self,
  pkgs,
  nixpkgs,
  home-manager,
  sops-nix,
}:
let
  development = import ./development.nix {
    inherit home-manager pkgs;
    inputs = self.inputs;
  };
in
{
  caveman = import ./caveman.nix {
    inherit pkgs;
    package = self.packages.${pkgs.stdenv.hostPlatform.system}.caveman;
  };
  ci-contract = import ./ci-contract.nix {
    inherit
      home-manager
      nixpkgs
      self
      pkgs
      ;
  };
  inherit development;
  opencode-desktop = development.tests.opencode-desktop;
  email = import ./email.nix {
    inherit home-manager pkgs sops-nix;
  };
  gpu = import ./gpu.nix { inherit pkgs nixpkgs home-manager; };
  secrets = import ./secrets.nix { inherit pkgs; };
  strata = import ./strata.nix {
    inherit pkgs;
    src = self.inputs.strata;
  };
  formatting = (import ./formatting.nix { inherit self pkgs; }).check;
  symlinks = import ./symlinks.nix { inherit self pkgs; };
  statix = import ./statix.nix { inherit self pkgs; };
  deadnix = import ./deadnix.nix { inherit self pkgs; };
}
