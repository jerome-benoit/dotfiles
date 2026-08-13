{
  config,
  lib,
  pkgs,
  inputs,
  ...
}:
let
  cfg = config.modules.development.qmd;
  system = pkgs.stdenv.hostPlatform.system;

  qmdPackage = inputs.qmd.packages.${system}.default or null;

  optionalPackages = config.modules.core.lib.mkOptionalPackages [
    {
      package = cfg.package;
      warning = "qmd: package not available for system ${system}";
    }
  ];
in
{
  options.modules.development.qmd = {
    enable = lib.mkEnableOption "qmd configuration";

    package = config.modules.core.lib.mkOptionalPackageOption {
      default = qmdPackage;
      defaultText = lib.literalExpression "inputs.qmd.packages.\${system}.default";
      description = "QMD CLI package";
    };
  };

  config = lib.mkIf cfg.enable {
    home.packages = optionalPackages.packages;
    warnings = optionalPackages.warnings;
  };
}
