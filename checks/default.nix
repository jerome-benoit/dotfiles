{
  self,
  pkgs,
}:
{
  formatting = (import ./formatting.nix { inherit self pkgs; }).check;
  statix = import ./statix.nix { inherit self pkgs; };
  deadnix = import ./deadnix.nix { inherit self pkgs; };
}
