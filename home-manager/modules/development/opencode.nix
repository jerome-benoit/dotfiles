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
  pins =
    (import ./pins {
      inherit lib;
      inherit (pkgs) fetchurl fetchzip;
    }).opencode;

  # Workaround: keep native dependency hashes separate from source updates.
  # Revalidate against upstream's hash bot after dependency or toolchain changes.
  # Remove when native builds validate upstream hashes with the followed nixpkgs.
  baseOpencodePackage =
    let
      package = inputs.opencode.packages.${system}.default or null;
      nodeModules = package.node_modules or null;
    in
    if nodeModules == null then
      package
    else
      package.override {
        node_modules = nodeModules.override { hash = pins.nodeModules.${system}; };
      };

  mkOpencodePackage =
    package:
    if package != null then
      package.overrideAttrs (previousAttrs: {
        # Workaround: Desktop discovers service.json, not service-prod.json.
        # Remove when upstream CLI and clients use the same service registry.
        env = (previousAttrs.env or { }) // {
          OPENCODE_CHANNEL = "latest";
        };

        # Workaround: native Node modules need libstdc++ at runtime on Linux.
        # Remove when upstream wraps the executable with its compiler runtime.
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
    if cfg.opencodePackage != null && desktop != null then
      # opencode-desktop builds with bare nixpkgs.legacyPackages and pins its own
      # electron, so the host nixpkgs config does not reach it.
      (desktop.override { opencode = cfg.opencodePackage; }).overrideAttrs (previousAttrs: {
        # Workaround: Desktop caches CLI binaries by version, ignoring Nix overrides.
        # Remove when upstream keys staged binaries by source identity.
        postPatch = (previousAttrs.postPatch or "") + ''
          substituteInPlace packages/desktop/src/main/service/cli-version.ts \
            --replace-fail \
              'return `''${version}-''${arch}`.replace(/[^a-zA-Z0-9._-]/g, "-")' \
              'return `''${version}-''${arch}-${builtins.baseNameOf (toString cfg.opencodePackage)}`.replace(/[^a-zA-Z0-9._-]/g, "-")'
        '';

        # Workaround: upstream stages the CLI outside the directory its Desktop build reads.
        # Remove when upstream's Nix staging matches packages/cli/dist.
        buildPhase =
          let
            staging = ''export OPENCODE_CLI_DIST="$TMPDIR/desktop-cli"'';
          in
          assert lib.assertMsg (lib.hasInfix staging previousAttrs.buildPhase)
            "OpenCode Desktop CLI staging changed; refresh the Nix workaround";
          lib.replaceStrings [ staging ] [ ''export OPENCODE_CLI_DIST="$PWD/../cli/dist"'' ]
            previousAttrs.buildPhase;
      })
    else
      null;

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

    opencodePackage =
      (config.modules.core.lib.mkOptionalPackageOption {
        default = baseOpencodePackage;
        defaultText = lib.literalExpression "inputs.opencode.packages.\${system}.default";
        description = ''
          OpenCode v2 TUI and CLI package using the upstream source build environment.
          The selected package receives the shared-service and Linux runtime adjustments.
        '';
        example = lib.literalExpression "inputs.opencode.packages.\${system}.default";
      })
      // {
        apply = mkOpencodePackage;
      };

    desktopPackage = config.modules.core.lib.mkOptionalPackageOption {
      default = null;
      defaultText = lib.literalExpression "null";
      description = "OpenCode Desktop package";
    };
  };

  config = lib.mkIf cfg.enable {
    modules.development.opencode.desktopPackage = lib.mkIf cfg.enableDesktop (
      lib.mkDefault mkDesktopPackage
    );

    home.packages = optionalPackages.packages;
    warnings = optionalPackages.warnings;
  };
}
