{
  self,
  pkgs,
  nixpkgs,
  home-manager,
  sops-nix,
}:
{
  ci-contract = import ./ci-contract.nix {
    inherit
      home-manager
      nixpkgs
      self
      pkgs
      ;
  };
  email = import ./email.nix {
    inherit home-manager pkgs sops-nix;
  };
  secrets = import ./secrets.nix { inherit pkgs; };
  formatting = (import ./formatting.nix { inherit self pkgs; }).check;
  symlinks = import ./symlinks.nix { inherit self pkgs; };
  statix = import ./statix.nix { inherit self pkgs; };
  deadnix = import ./deadnix.nix { inherit self pkgs; };
}
