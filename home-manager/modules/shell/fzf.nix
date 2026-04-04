{
  config,
  lib,
  ...
}:

let
  cfg = config.modules.shell.fzf;
  mkPlatformPackage = config.modules.core.lib.mkPlatformPackage;
in
{
  options.modules.shell.fzf = {
    enable = lib.mkEnableOption "fzf configuration";
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = config.modules.shell.fd.enable;
        message = "fzf: fd module must be enabled (set modules.shell.fd.enable = true)";
      }
    ];

    programs.fzf = {
      enable = true;
      package = mkPlatformPackage "fzf" { version = "0.67.0"; };
      enableZshIntegration = false;
      defaultCommand = "fd --type f";
      fileWidgetCommand = "fd --type f";
      changeDirWidgetCommand = "fd --type d";
    };
  };
}
