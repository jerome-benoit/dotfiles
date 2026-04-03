{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.shell.zoxide;
  mkPlatformPackage = config.modules.core.lib.mkPlatformPackage;
in
{
  options.modules.shell.zoxide = {
    enable = lib.mkEnableOption "zoxide configuration";
  };

  config = lib.mkIf cfg.enable {
    programs.zoxide = {
      enable = true;
      package = mkPlatformPackage "zoxide" { };
      enableZshIntegration = false;
    };
  };
}
