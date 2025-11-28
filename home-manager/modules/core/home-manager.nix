{ config, lib, ... }:
let
  cfg = config.modules.core.home-manager;
in
{
  options.modules.core.home-manager = {
    enable = lib.mkEnableOption "home-manager configuration";
  };

  config = lib.mkIf cfg.enable {
    programs.home-manager.enable = true;
  };
}
