{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.shell.direnv;
  mkPlatformPackage = config.modules.core.lib.mkPlatformPackage;
in
{
  options.modules.shell.direnv = {
    enable = lib.mkEnableOption "direnv configuration";
  };

  config = lib.mkIf cfg.enable {
    programs.direnv = {
      enable = true;
      package = mkPlatformPackage "direnv" { };
      nix-direnv.enable = true;
      enableZshIntegration = false;
    };
  };
}
