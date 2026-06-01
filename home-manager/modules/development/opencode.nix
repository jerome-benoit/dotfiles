{
  config,
  lib,
  pkgs,
  self,
  inputs,
  ...
}:
let
  cfg = config.modules.development.opencode;
  system = pkgs.stdenv.hostPlatform.system;

  opencodePatches = [
    (self + "/patches/opencode/relax-bun-version-check.patch")
    (self + "/patches/opencode/expose-v2-css-exports.patch")
  ];

  withOpencodePatches =
    drv:
    drv.overrideAttrs (oldAttrs: {
      patches = (oldAttrs.patches or [ ]) ++ opencodePatches;
    });

  baseOpencodePackage = inputs.opencode.packages.${system}.default or null;

  opencodePackage =
    if baseOpencodePackage != null then
      withOpencodePatches (
        baseOpencodePackage.overrideAttrs (oldAttrs: {
          # Workaround for https://github.com/anomalyco/opencode/issues/18447
          postFixup =
            (oldAttrs.postFixup or "")
            + lib.optionalString pkgs.stdenv.hostPlatform.isLinux ''
              wrapProgram "$out/bin/opencode" \
                --prefix LD_LIBRARY_PATH : ${pkgs.stdenv.cc.cc.lib}/lib
            '';
        })
      )
    else
      null;

  mkDesktopPackage =
    let
      desktop = inputs.opencode.packages.${system}.opencode-desktop or null;
    in
    if desktop != null then desktop.override { opencode = opencodePackage; } else null;
in
{
  options.modules.development.opencode = {
    enable = lib.mkEnableOption "opencode configuration";

    enableDesktop = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Whether to enable OpenCode Desktop integration";
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
      default = null;
      defaultText = lib.literalExpression "null";
      description = "OpenCode Desktop package";
    };
  };

  config = lib.mkIf cfg.enable {
    modules.development.opencode.desktopPackage = lib.mkIf cfg.enableDesktop mkDesktopPackage;

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
