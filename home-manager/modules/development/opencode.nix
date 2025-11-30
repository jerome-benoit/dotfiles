{
  config,
  lib,
  pkgs,
  inputs,
  ...
}:
let
  cfg = config.modules.development.opencode;
  system = pkgs.stdenv.hostPlatform.system;
in
{
  options.modules.development.opencode = {
    enable = lib.mkEnableOption "opencode configuration";
    package = lib.mkOption {
      type = lib.types.package;
      default = inputs.opencode.packages.${system}.default;
      description = "The opencode package";
    };
  };

  config = lib.mkIf cfg.enable {
    home.packages = [
      cfg.package
    ];
  };
}
