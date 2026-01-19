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
in
{
  options.modules.development.openspec = {
    enable = lib.mkEnableOption "openspec configuration";

    openspecPackage = lib.mkOption {
      type = lib.types.nullOr lib.types.package;
      default = inputs.openspec.packages.${system}.default or null;
      defaultText = lib.literalExpression "inputs.openspec.packages.\${system}.default";
      description = "OpenSpec CLI package";
      example = lib.literalExpression "inputs.openspec.packages.\${system}.default";
    };
  };

  config = lib.mkIf cfg.enable {
    home.packages = lib.optional (cfg.openspecPackage != null) cfg.openspecPackage;

    warnings = lib.optional (
      cfg.openspecPackage == null
    ) "openspec: package not available for system ${system}";
  };
}
