{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.programs.glow;
  mkSystemPackage = config.modules.core.lib.mkSystemPackage;
in
{
  options.modules.programs.glow = {
    enable = lib.mkEnableOption "glow configuration";
  };

  config = lib.mkIf cfg.enable {
    home.packages = if pkgs.stdenv.isDarwin then [ pkgs.glow ] else [ (mkSystemPackage "glow" { }) ];

    xdg.configFile."glow/glow.yml".text = lib.generators.toYAML { } {
      style = "auto";
      mouse = true;
      pager = true;
      width = 100;
      all = false;
    };
  };
}
