{
  config,
  lib,
  pkgs,
  inputs,
  ...
}:
let
  cfg = config.modules.development.opencode;
  system = pkgs.stdenv.hostPlatform.system;
in
{
  options.modules.development.opencode = {
    enable = lib.mkEnableOption "opencode configuration";

    package = lib.mkOption {
      type = lib.types.nullOr lib.types.package;
      default = inputs.opencode.packages.${system}.default or null;
      defaultText = lib.literalExpression "inputs.opencode.packages.\${system}.default";
      description = "OpenCode CLI package from SST";
      example = lib.literalExpression "inputs.opencode.packages.\${system}.default";
    };
  };

  config = lib.mkIf cfg.enable {
    home.packages = lib.optional (cfg.package != null) cfg.package;

    warnings = lib.optional (
      cfg.package == null
    ) "opencode: Package not available for system ${system}";
  };
}
