{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.shell.ripgrep;
  systemRipgrep = pkgs.runCommand "ripgrep-system" { meta.mainProgram = "rg"; } "mkdir -p $out";
in
{
  options.modules.shell.ripgrep = {
    enable = lib.mkEnableOption "ripgrep configuration";
  };

  config = lib.mkIf cfg.enable {
    programs.ripgrep = {
      enable = true;
      package = if pkgs.stdenv.isDarwin then pkgs.ripgrep else systemRipgrep;
    };
  };
}
