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
  upstreamOpencodePackage = inputs.opencode.packages.${system}.default or null;
  # Workaround: the pinned source ships stale node_modules hashes.
  # Reuse native hashes from https://github.com/anomalyco/opencode/pull/66375.
  # Its aba07835 revision has the same dependency inputs as this pin.
  # Remove when the pinned source supplies valid hashes on all supported systems.
  dependencyHashes = {
    x86_64-linux = "sha256-1XC9ohZg6TT/e4j3j0SYBThXuaCwGrAO3tWb1n50Nx4=";
    aarch64-linux = "sha256-hrtbp7DyqvCAiZin0GIAr1QspydyScGezmYZGPkw9L4=";
    aarch64-darwin = "sha256-mMlIfMs7L3yNW6DV5ggMtd7NJI1z1lmM0e+TF6wJbqI=";
  };
  baseOpencodePackage =
    if upstreamOpencodePackage == null then
      null
    else
      upstreamOpencodePackage.overrideAttrs (previousAttrs: {
        node_modules = previousAttrs.node_modules.overrideAttrs (dependencyAttrs: {
          outputHash =
            if (inputs.opencode.rev or null) == "a152d11d072499a97593107bf90379b83aad107f" then
              dependencyHashes.${system} or dependencyAttrs.outputHash
            else
              dependencyAttrs.outputHash;
          # Workaround: recursive copies already include nested node_modules.
          # Remove when upstream prunes those descendants during installation.
          installPhase =
            let
              copy = ''find . -type d -name node_modules -exec cp -R --parents {} $out \;'';
            in
            assert lib.assertMsg (lib.hasInfix copy dependencyAttrs.installPhase)
              "OpenCode dependency installation changed; refresh the Nix workaround";
            lib.replaceStrings
              [ copy ]
              [ ''find . -type d -name node_modules -prune -exec cp -R --parents {} $out \;'' ]
              dependencyAttrs.installPhase;
        });
      });

  mkOpencodePackage =
    package:
    if package != null then
      let
        compiledPackage = package.overrideAttrs (previousAttrs: {
          # Workaround: Desktop discovers service.json, not service-prod.json.
          # Remove when upstream CLI and clients use the same service registry.
          env = (previousAttrs.env or { }) // {
            OPENCODE_CHANNEL = "latest";
          };
        });
      in
      if pkgs.stdenv.hostPlatform.isLinux then
        pkgs.symlinkJoin (
          {
            name = compiledPackage.name;
            paths = [ compiledPackage ];
            # Desktop validates the copied CLI as a native executable.
            nativeBuildInputs = [ pkgs.makeBinaryWrapper ];
            # Workaround: native Node modules need libstdc++ at runtime on Linux.
            # Remove when upstream wraps the executable with its compiler runtime.
            postBuild = ''
              # Own bin even when a selected package links that directory elsewhere.
              rm -rf "$out/bin"
              mkdir "$out/bin"
              cp -rs "${compiledPackage}/bin/." "$out/bin/"
              for executable in "$out"/bin/*; do
                if [ "$executable" != "$out/bin/opencode" ] \
                  && [ "$executable" -ef "$out/bin/opencode" ]; then
                  rm "$executable"
                  ln -s opencode "$executable"
                fi
              done
              rm "$out/bin/opencode"
              makeBinaryWrapper "${compiledPackage}/bin/opencode" "$out/bin/opencode" \
                --prefix LD_LIBRARY_PATH : ${pkgs.stdenv.cc.cc.lib}/lib
            '';
            passthru =
              (compiledPackage.passthru or { })
              // lib.filterAttrs (
                name: _:
                builtins.elem name [
                  "env"
                  "node_modules"
                  "patches"
                  "src"
                ]
              ) compiledPackage
              // {
                inherit compiledPackage;
              };
            inherit (compiledPackage) meta;
          }
          // lib.filterAttrs (
            name: _:
            builtins.elem name [
              "pname"
              "version"
            ]
          ) compiledPackage
        )
      else
        compiledPackage
    else
      null;

  mkDesktopPackage =
    let
      desktop = inputs.opencode.packages.${system}.opencode-desktop or null;
    in
    if cfg.opencodePackage != null && desktop != null then
      # Desktop selects its Electron major from package.json and resolves it in
      # the flake's bare nixpkgs.legacyPackages, not the host's configured pkgs.
      (desktop.override { opencode = cfg.opencodePackage; }).overrideAttrs (previousAttrs: {
        # Workaround: version-only CLI stages collide across Nix builds.
        # Remove with the substitution below when upstream isolates distinct CLI
        # builds of the same version, architecture, and channel, and retains both
        # bundled and adopted stages for the current architecture.
        patches = (previousAttrs.patches or [ ]) ++ [ ../../../patches/opencode-nix-cli-stages.patch ];
        postPatch = (previousAttrs.postPatch or "") + ''
          substituteInPlace packages/desktop/src/main/service/desktop-cli.ts \
            --replace-fail '@opencode-nix-cli-identity@' '${builtins.baseNameOf (toString cfg.opencodePackage)}'
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
    enable = lib.mkEnableOption "OpenCode configuration";

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
