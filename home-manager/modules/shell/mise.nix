{
  config,
  lib,
  ...
}:

let
  cfg = config.modules.shell.mise;
  mkPlatformPackage = config.modules.core.lib.mkPlatformPackage;
in
{
  options.modules.shell.mise = {
    enable = lib.mkEnableOption "mise configuration";
  };

  config = lib.mkIf cfg.enable {
    programs.mise = {
      enable = true;
      package = mkPlatformPackage "mise" { nixOn = "all"; };
      enableZshIntegration = false;
    };
  };
}
