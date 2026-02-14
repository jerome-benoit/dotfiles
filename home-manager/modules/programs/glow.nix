{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.programs.glow;
  mkSystemPackage = config.modules.core.lib.mkSystemPackage;

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
    home.packages = if pkgs.stdenv.isDarwin then [ pkgs.glow ] else [ (mkSystemPackage "glow" { }) ];

    home.file = lib.mkIf pkgs.stdenv.isDarwin {
      "Library/Preferences/glow/glow.yml".source = glowConfig;
    };

    xdg.configFile = lib.mkIf pkgs.stdenv.isLinux {
      "glow/glow.yml".source = glowConfig;
    };
  };
}
