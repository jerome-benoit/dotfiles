{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.development.bun;
in
{
  options.modules.development.bun = {
    enable = lib.mkEnableOption "bun configuration";
  };

  config = lib.mkIf cfg.enable {
    programs.bun = {
      enable = true;
    };
  };
}
