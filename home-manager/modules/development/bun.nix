{
  config,
  lib,
  ...
}:

let
  cfg = config.modules.development.bun;
in
{
  options.modules.development.bun = {
    enable = lib.mkEnableOption "Bun configuration";
  };

  config = lib.mkIf cfg.enable {
    programs.bun = {
      enable = true;
    };
  };
}
