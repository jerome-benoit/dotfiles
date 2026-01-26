{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.shell.eza;
  mkSystemPackage = config.modules.core.lib.mkSystemPackage;
in
{
  options.modules.shell.eza = {
    enable = lib.mkEnableOption "eza configuration";
  };

  config = lib.mkIf cfg.enable {
    programs.eza = {
      enable = true;
      package = if pkgs.stdenv.isDarwin then pkgs.eza else mkSystemPackage "eza" { };
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
