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

  baseOpencodePackage = inputs.opencode.packages.${system}.default or null;

  opencodePackage =
    if baseOpencodePackage != null then
      baseOpencodePackage.overrideAttrs (previousAttrs: {
        # Native Node modules require libstdc++ at runtime on Linux.
        postFixup =
          (previousAttrs.postFixup or "")
          + lib.optionalString pkgs.stdenv.hostPlatform.isLinux ''
            wrapProgram "$out/bin/opencode" \
              --prefix LD_LIBRARY_PATH : ${pkgs.stdenv.cc.cc.lib}/lib
          '';
      })
    else
      null;

  mkDesktopPackage =
    let
      desktop = inputs.opencode.packages.${system}.opencode-desktop or null;
    in
    if desktop != null then desktop.override { opencode = opencodePackage; } else null;

  optionalPackages = config.modules.core.lib.mkOptionalPackages [
    {
      package = cfg.opencodePackage;
      warning = "opencode: TUI and CLI package not available for system ${system}";
    }
    {
      package = cfg.desktopPackage;
      enabled = cfg.enableDesktop;
      warning = "opencode: Desktop package not available for system ${system}";
    }
  ];
in
{
  options.modules.development.opencode = {
    enable = lib.mkEnableOption "opencode configuration";

    enableDesktop = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Whether to enable OpenCode Desktop integration";
    };

    opencodePackage = config.modules.core.lib.mkOptionalPackageOption {
      default = opencodePackage;
      defaultText = lib.literalExpression "inputs.opencode.packages.\${system}.default";
      description = "OpenCode TUI and CLI package";
      example = lib.literalExpression "inputs.opencode.packages.\${system}.default";
    };

    desktopPackage = config.modules.core.lib.mkOptionalPackageOption {
      default = null;
      defaultText = lib.literalExpression "null";
      description = "OpenCode Desktop package";
    };
  };

  config = lib.mkIf cfg.enable {
    modules.development.opencode.desktopPackage = lib.mkIf cfg.enableDesktop mkDesktopPackage;

    home.packages = optionalPackages.packages;
    warnings = optionalPackages.warnings;
  };
}
