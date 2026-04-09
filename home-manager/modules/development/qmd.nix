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
in
{
  options.modules.development.qmd = {
    enable = lib.mkEnableOption "qmd configuration";

    package = lib.mkOption {
      type = lib.types.nullOr lib.types.package;
      default = inputs.qmd.packages.${system}.default or null;
      defaultText = lib.literalExpression "inputs.qmd.packages.\${system}.default";
      description = "QMD CLI package";
      example = lib.literalExpression "inputs.qmd.packages.\${system}.default";
    };
  };

  config = lib.mkIf cfg.enable {
    home.packages = lib.optional (cfg.package != null) cfg.package;

    warnings = lib.optional (cfg.package == null) "qmd: package not available for system ${system}";
  };
}
