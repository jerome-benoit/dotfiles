{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.development.gh;
in
{
  options.modules.development.gh = {
    enable = lib.mkEnableOption "gh configuration";
  };

  config = lib.mkIf cfg.enable {
    programs.gh = {
      enable = true;
      extensions = with pkgs; [
        gh-dash
      ];
    };
  };
}
