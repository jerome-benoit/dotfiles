{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.programs.glow;
  mkPlatformPackage = config.modules.core.lib.mkPlatformPackage;

  glowConfig = (pkgs.formats.yaml { }).generate "glow.yml" {
    style = "auto";
    mouse = true;
    pager = true;
    width = 100;
    all = false;
  };
in
{
  options.modules.programs.glow = {
    enable = lib.mkEnableOption "glow configuration";
  };

  config = lib.mkIf cfg.enable {
    home.packages = [ (mkPlatformPackage "glow" { }) ];

    home.file = lib.mkIf pkgs.stdenv.hostPlatform.isDarwin {
      "Library/Preferences/glow/glow.yml".source = glowConfig;
    };

    xdg.configFile = lib.mkIf pkgs.stdenv.hostPlatform.isLinux {
      "glow/glow.yml".source = glowConfig;
    };
  };
}
