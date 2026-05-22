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

  baseOpenspecPackage = inputs.openspec.packages.${system}.default or null;

  openspecPackage =
    if baseOpenspecPackage != null then
      baseOpenspecPackage.overrideAttrs (_: {
        nativeBuildInputs = with pkgs; [
          nodejs_22
          npmHooks.npmInstallHook
          pnpmConfigHook
          pnpm_9
        ];
      })
    else
      null;
in
{
  options.modules.development.openspec = {
    enable = lib.mkEnableOption "openspec configuration";

    package = lib.mkOption {
      type = lib.types.nullOr lib.types.package;
      default = openspecPackage;
      defaultText = lib.literalExpression "inputs.openspec.packages.\${system}.default";
      description = "OpenSpec CLI package";
      example = lib.literalExpression "inputs.openspec.packages.\${system}.default";
    };
  };

  config = lib.mkIf cfg.enable {
    home.packages = lib.optional (cfg.package != null) cfg.package;

    warnings = lib.optional (
      cfg.package == null
    ) "openspec: package not available for system ${system}";
  };
}
