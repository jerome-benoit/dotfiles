{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.shell.zoxide;
  systemZoxide = pkgs.runCommand "zoxide-system" { meta.mainProgram = "zoxide"; } "mkdir -p $out";
in
{
  options.modules.shell.zoxide = {
    enable = lib.mkEnableOption "zoxide configuration";
  };

  config = lib.mkIf cfg.enable {
    programs.zoxide = {
      enable = true;
      package = if pkgs.stdenv.isDarwin then pkgs.zoxide else systemZoxide;
      enableZshIntegration = false;
    };
  };
}
