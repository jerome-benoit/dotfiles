{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.development.claudeCode;
in
{
  options.modules.development.claudeCode = {
    enable = lib.mkEnableOption "claude-code configuration";
  };

  config = lib.mkIf cfg.enable {
    home.packages = [ pkgs.claude-code ];
  };
}
