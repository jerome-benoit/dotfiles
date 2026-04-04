{
  config,
  lib,
  ...
}:

let
  cfg = config.modules.programs.btop;
  mkPlatformPackage = config.modules.core.lib.mkPlatformPackage;
in
{
  options.modules.programs.btop = {
    enable = lib.mkEnableOption "btop configuration";
  };

  config = lib.mkIf cfg.enable {
    programs.btop = {
      enable = true;
      package = mkPlatformPackage "btop" { };
    };
  };
}
