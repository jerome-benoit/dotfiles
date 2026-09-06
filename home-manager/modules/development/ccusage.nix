{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.modules.development.ccusage;
  system = pkgs.stdenv.hostPlatform.system;

  optionalPackages = config.modules.core.lib.mkOptionalPackages [
    {
      package = cfg.package;
      warning = "ccusage: package not available for system ${system}";
    }
  ];
in
{
  options.modules.development.ccusage = {
    enable = lib.mkEnableOption "ccusage configuration";

    package = config.modules.core.lib.mkOptionalPackageOption {
      default = pkgs.ccusage;
      defaultText = lib.literalExpression "pkgs.ccusage";
      description = "ccusage CLI package";
    };
  };

  config = lib.mkIf cfg.enable {
    home.packages = optionalPackages.packages;
    warnings = optionalPackages.warnings;
  };
}
