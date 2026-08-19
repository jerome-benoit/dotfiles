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
  pnpmPackage = pkgs.pnpm_10;
  pnpmDepsHash = "sha256-n+tFm3GvMV3vH2A+1LTJbqxzgk5wOCJ7kng/0y56Zlk=";

  openspecPackage =
    if baseOpenspecPackage != null then
      baseOpenspecPackage.overrideAttrs (
        finalAttrs: _: {
          pnpmDeps = pkgs.fetchPnpmDeps {
            inherit (finalAttrs) pname version src;
            pnpm = pnpmPackage;
            fetcherVersion = 3;
            hash = pnpmDepsHash;
          };

          nativeBuildInputs = with pkgs; [
            nodejs_22
            npmHooks.npmInstallHook
            pnpmConfigHook
            pnpmPackage
          ];
        }
      )
    else
      null;

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
