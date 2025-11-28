{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.programs.btop;
  systemBtop = pkgs.runCommand "btop-system" { meta.mainProgram = "btop"; } "mkdir -p $out";
in
{
  options.modules.programs.btop = {
    enable = lib.mkEnableOption "btop configuration";
  };

  config = lib.mkIf cfg.enable {
    programs.btop = {
      enable = true;
      package = if pkgs.stdenv.isDarwin then pkgs.btop else systemBtop;
    };
  };
}
