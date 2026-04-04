{
  self,
  pkgs,
}:
{
  formatting = (import ./formatting.nix { inherit self pkgs; }).check;
  symlinks = import ./symlinks.nix { inherit self pkgs; };
  statix = import ./statix.nix { inherit self pkgs; };
  deadnix = import ./deadnix.nix { inherit self pkgs; };
}
