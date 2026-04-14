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

  baseOpencodePackage = inputs.opencode.packages.${system}.default or null;

  opencodePackage =
    if baseOpencodePackage != null then
      baseOpencodePackage.overrideAttrs (oldAttrs: {
        patches = (oldAttrs.patches or [ ]) ++ [
          (self + "/patches/opencode/relax-bun-version-check.patch")
          # https://github.com/anomalyco/opencode/pull/12822
          (self + "/patches/opencode/proxy-env-to-process-env.patch")
        ];
        # Workaround for https://github.com/anomalyco/opencode/issues/18447
        postFixup =
          (oldAttrs.postFixup or "")
          + lib.optionalString pkgs.stdenv.hostPlatform.isLinux ''
            wrapProgram "$out/bin/opencode" \
              --prefix LD_LIBRARY_PATH : ${pkgs.stdenv.cc.cc.lib}/lib
          '';
      })
    else
      null;

  desktopPackage =
    let
      desktop = inputs.opencode.packages.${system}.desktop or null;
      outputHashes = import ./opencode-hashes.nix;
    in
    if desktop != null then
      (desktop.override { opencode = opencodePackage; }).overrideAttrs (_: {
        cargoDeps = pkgs.rustPlatform.importCargoLock {
          lockFile = inputs.opencode + "/packages/desktop/src-tauri/Cargo.lock";
          inherit outputHashes;
        };
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
      description = "OpenCode Desktop integration";
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
      default = desktopPackage;
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
