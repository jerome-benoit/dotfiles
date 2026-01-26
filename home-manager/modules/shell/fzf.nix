{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.shell.fzf;
  mkSystemPackage = config.modules.core.lib.mkSystemPackage;
in
{
  options.modules.shell.fzf = {
    enable = lib.mkEnableOption "fzf configuration";
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = config.modules.shell.fd.enable;
        message = "fzf: fd module must be enabled (modules.shell.fd.enable = true)";
      }
    ];

    programs.fzf = {
      enable = true;
      package = if pkgs.stdenv.isDarwin then pkgs.fzf else mkSystemPackage "fzf" { };
      enableZshIntegration = false;
      defaultCommand = "fd --type f";
      fileWidgetCommand = "fd --type f";
      changeDirWidgetCommand = "fd --type d";
    };
  };
}
