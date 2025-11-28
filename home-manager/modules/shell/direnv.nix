{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.shell.direnv;
  systemDirenv = pkgs.runCommand "direnv-system" { meta.mainProgram = "direnv"; } "mkdir -p $out";
in
{
  options.modules.shell.direnv = {
    enable = lib.mkEnableOption "direnv configuration";
  };

  config = lib.mkIf cfg.enable {
    programs.direnv = {
      enable = true;
      package = if pkgs.stdenv.isDarwin then pkgs.direnv else systemDirenv;
      nix-direnv.enable = true;
      enableZshIntegration = false;
    };
  };
}
