{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.shell.direnv;
  mkSystemPackage = config.modules.core.lib.mkSystemPackage;
in
{
  options.modules.shell.direnv = {
    enable = lib.mkEnableOption "direnv configuration";
  };

  config = lib.mkIf cfg.enable {
    programs.direnv = {
      enable = true;
      package = if pkgs.stdenv.isDarwin then pkgs.direnv else mkSystemPackage "direnv" { };
      nix-direnv.enable = true;
      enableZshIntegration = false;
    };
  };
}
