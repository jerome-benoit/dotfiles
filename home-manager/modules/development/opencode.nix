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

  opencodePackage =
    if inputs.opencode.packages.${system}.default or null != null then
      inputs.opencode.packages.${system}.default.overrideAttrs (oldAttrs: {
        patches = (oldAttrs.patches or [ ]) ++ [
          ../../../patches/opencode-disable-bun-version-check.patch
        ];
      })
    else
      null;
in
{
  options.modules.development.opencode = {
    enable = lib.mkEnableOption "opencode configuration";

    enableDesktop = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "OpenCode Desktop package";
    };

    opencodePackage = lib.mkOption {
      type = lib.types.nullOr lib.types.package;
      default = opencodePackage;
      defaultText = lib.literalExpression "inputs.opencode.packages.\${system}.default";
      description = "OpenCode TUI and CLI package";
      example = lib.literalExpression "inputs.opencode.packages.\${system}.default";
    };

    desktopPackage = lib.mkOption {
      type = lib.types.nullOr lib.types.package;
      default = inputs.opencode.packages.${system}.desktop or null;
      defaultText = lib.literalExpression "inputs.opencode.packages.\${system}.desktop";
      description = "OpenCode Desktop package";
      example = lib.literalExpression "inputs.opencode.packages.\${system}.desktop";
    };
  };

  config = lib.mkIf cfg.enable {
    home.packages =
      lib.optional (cfg.opencodePackage != null) cfg.opencodePackage
      ++ lib.optional (cfg.enableDesktop && cfg.desktopPackage != null) cfg.desktopPackage;

    warnings =
      lib.optional (
        cfg.opencodePackage == null
      ) "opencode: TUI and CLI package not available for system ${system}"
      ++ lib.optional (
        cfg.enableDesktop && cfg.desktopPackage == null
      ) "opencode: Desktop package not available for system ${system}";
  };
}
