{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.shell.fzf;
  systemFzf = pkgs.runCommand "fzf-system" {
    version = "0.60.0";
    meta.mainProgram = "fzf";
  } "mkdir -p $out";
in
{
  options.modules.shell.fzf = {
    enable = lib.mkEnableOption "fzf configuration";
  };

  config = lib.mkIf cfg.enable {
    programs.fzf = {
      enable = true;
      package = if pkgs.stdenv.isDarwin then pkgs.fzf else systemFzf;
      enableZshIntegration = false;
      defaultCommand = "fd --type f";
      fileWidgetCommand = "fd --type f";
    };
  };
}
