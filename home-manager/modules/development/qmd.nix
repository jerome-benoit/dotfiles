{
  config,
  lib,
  pkgs,
  inputs,
  self,
  ...
}:
let
  cfg = config.modules.development.qmd;
  system = pkgs.stdenv.hostPlatform.system;
  isLinux = pkgs.stdenv.hostPlatform.isLinux;

  baseQmdPackage = inputs.qmd.packages.${system}.default or null;

  # https://github.com/tobi/qmd/pull/574
  qmdPackage =
    if baseQmdPackage != null then
      baseQmdPackage.overrideAttrs (old: {
        patches = (old.patches or [ ]) ++ [
          (self + "/patches/qmd/fix-nixos-llama-build.patch")
        ];
      })
    else
      null;
in
{
  options.modules.development.qmd = {
    enable = lib.mkEnableOption "qmd configuration";

    package = lib.mkOption {
      type = lib.types.nullOr lib.types.package;
      default = qmdPackage;
      defaultText = lib.literalExpression "inputs.qmd.packages.\${system}.default";
      description = "QMD CLI package";
    };
  };

  config = lib.mkIf cfg.enable {
    home.packages = lib.optional (cfg.package != null) cfg.package;

    warnings = lib.optional (cfg.package == null) "qmd: package not available for system ${system}";
  };
}
