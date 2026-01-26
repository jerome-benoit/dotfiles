{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.shell.fd;
  mkSystemPackage = config.modules.core.lib.mkSystemPackage;
in
{
  options.modules.shell.fd = {
    enable = lib.mkEnableOption "fd configuration";
  };

  config = lib.mkIf cfg.enable {
    programs.fd = {
      enable = true;
      package = if pkgs.stdenv.isDarwin then pkgs.fd else mkSystemPackage "fd" { };
    };
  };
}
