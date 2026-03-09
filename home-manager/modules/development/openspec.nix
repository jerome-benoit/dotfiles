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

  nodejs_20 = pkgs.nodejs_20.override {
    nodejs-slim = pkgs.nodejs-slim_20.overrideAttrs { doCheck = false; };
  };
  openspecBase = inputs.openspec.packages.${system}.default or null;
  openspec =
    if openspecBase != null then
      openspecBase.overrideAttrs (old: {
        nativeBuildInputs = map (drv: if (drv.pname or "") == "nodejs" then nodejs_20 else drv) (
          old.nativeBuildInputs or [ ]
        );
      })
    else
      null;
in
{
  options.modules.development.openspec = {
    enable = lib.mkEnableOption "openspec configuration";

    openspecPackage = lib.mkOption {
      type = lib.types.nullOr lib.types.package;
      default = openspec;
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
