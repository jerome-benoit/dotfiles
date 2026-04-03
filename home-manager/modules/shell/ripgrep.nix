{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.shell.ripgrep;
  mkPlatformPackage = config.modules.core.lib.mkPlatformPackage;
in
{
  options.modules.shell.ripgrep = {
    enable = lib.mkEnableOption "ripgrep configuration";
  };

  config = lib.mkIf cfg.enable {
    programs.ripgrep = {
      enable = true;
      package = mkPlatformPackage "ripgrep" { mainProgram = "rg"; };
    };
  };
}
