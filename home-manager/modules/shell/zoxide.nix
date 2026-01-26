{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.shell.zoxide;
  mkSystemPackage = config.modules.core.lib.mkSystemPackage;
in
{
  options.modules.shell.zoxide = {
    enable = lib.mkEnableOption "zoxide configuration";
  };

  config = lib.mkIf cfg.enable {
    programs.zoxide = {
      enable = true;
      package = if pkgs.stdenv.isDarwin then pkgs.zoxide else mkSystemPackage "zoxide" { };
      enableZshIntegration = false;
    };
  };
}
