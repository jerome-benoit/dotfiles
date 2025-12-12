{
  self,
  pkgs,
  home-manager,
  arch,
}:
{
  formatting = import ./formatting.nix { inherit self pkgs; };
  home-config = import ./home-config.nix {
    inherit
      self
      pkgs
      home-manager
      arch
      ;
  };
  symlinks = import ./symlinks.nix { inherit self pkgs; };
}
