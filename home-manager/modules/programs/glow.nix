{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.programs.glow;
  systemGlow = pkgs.runCommand "glow-system" { meta.mainProgram = "glow"; } "mkdir -p $out";
in
{
  options.modules.programs.glow = {
    enable = lib.mkEnableOption "glow configuration";
  };

  config = lib.mkIf cfg.enable {
    home.packages = [ (if pkgs.stdenv.isDarwin then pkgs.glow else systemGlow) ];

    home.file.".config/glow/glow.yml".text = lib.generators.toYAML { } {
      style = "auto";
      mouse = true;
      pager = true;
      width = 100;
      all = false;
    };
  };
}
