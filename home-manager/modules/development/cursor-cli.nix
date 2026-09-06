{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.modules.development.cursorCli;
  system = pkgs.stdenv.hostPlatform.system;

  optionalPackages = config.modules.core.lib.mkOptionalPackages [
    {
      package = cfg.package;
      warning = "cursorCli: package not available for system ${system}";
    }
  ];
in
{
  options.modules.development.cursorCli = {
    enable = lib.mkEnableOption "cursor-cli configuration";

    package = config.modules.core.lib.mkOptionalPackageOption {
      default = pkgs.cursor-cli;
      defaultText = lib.literalExpression "pkgs.cursor-cli";
      description = "Cursor CLI package";
    };
  };

  config = lib.mkIf cfg.enable {
    home.packages = optionalPackages.packages;
    warnings = optionalPackages.warnings;
  };
}
