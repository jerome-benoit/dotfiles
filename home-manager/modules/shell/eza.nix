{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.shell.eza;
  systemEza = pkgs.runCommand "eza-system" { meta.mainProgram = "eza"; } "mkdir -p $out";
in
{
  options.modules.shell.eza = {
    enable = lib.mkEnableOption "eza configuration";
  };

  config = lib.mkIf cfg.enable {
    programs.eza = {
      enable = true;
      package = if pkgs.stdenv.isDarwin then pkgs.eza else systemEza;
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
