{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.shell.fd;
  mkPlatformPackage = config.modules.core.lib.mkPlatformPackage;
in
{
  options.modules.shell.fd = {
    enable = lib.mkEnableOption "fd configuration";
  };

  config = lib.mkIf cfg.enable {
    programs.fd = {
      enable = true;
      package = mkPlatformPackage "fd" { };
    };
  };
}
