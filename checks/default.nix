{
  self,
  pkgs,
  home-manager,
  arch,
}:
{
  formatting = (import ./formatting.nix { inherit self pkgs; }).check;
  symlinks = import ./symlinks.nix { inherit self pkgs; };
}
