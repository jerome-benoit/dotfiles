{
  config,
  lib,
  ...
}:

let
  cfg = config.modules.shell.eza;
  mkPlatformPackage = config.modules.core.lib.mkPlatformPackage;
in
{
  options.modules.shell.eza = {
    enable = lib.mkEnableOption "eza configuration";
  };

  config = lib.mkIf cfg.enable {
    programs.eza = {
      enable = true;
      package = mkPlatformPackage "eza" { };
      enableZshIntegration = false;
      git = true;
      icons = "auto";
      extraOptions = [
        "--group-directories-first"
        "--header"
      ];
    };
  };
}
