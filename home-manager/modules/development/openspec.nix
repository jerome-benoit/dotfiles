{
  config,
  lib,
  pkgs,
  inputs,
  ...
}:
let
  cfg = config.modules.development.openspec;
  system = pkgs.stdenv.hostPlatform.system;

  openspecPackage = inputs.openspec.packages.${system}.default or null;

  optionalPackages = config.modules.core.lib.mkOptionalPackages [
    {
      package = cfg.package;
      warning = "openspec: package not available for system ${system}";
    }
  ];
in
{
  options.modules.development.openspec = {
    enable = lib.mkEnableOption "openspec configuration";

    package = config.modules.core.lib.mkOptionalPackageOption {
      default = openspecPackage;
      defaultText = lib.literalExpression "inputs.openspec.packages.\${system}.default";
      description = "OpenSpec CLI package";
      example = lib.literalExpression "inputs.openspec.packages.\${system}.default";
    };
  };

  config = lib.mkIf cfg.enable {
    home.packages = optionalPackages.packages;
    warnings = optionalPackages.warnings;
  };
}
