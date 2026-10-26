{
  lib,
  pkgs,
  stdenvNoCC,
  fetchurl,
  fetchzip,
  nodejs_22,
  makeWrapper,
  git,
  bash,
  callPackage,
  registrationProfile ? null,
}:
let
  pins = (import ../pins { inherit lib fetchurl fetchzip; }).caveman;
  runtime = callPackage ./runtime.nix { inherit pins; };
  installerSource = stdenvNoCC.mkDerivation {
    pname = "caveman-installer-source";
    inherit (pins) version;
    src = pins.src;
    # Workaround: installers persist generation-specific paths and share Claude payloads.
    # Remove when upstream supports durable paths and profile-local ownership.
    patches = [ ../../../../patches/caveman-nix-installer-paths.patch ];
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      mkdir -p "$out"
      cp -r . "$out/"
      runHook postInstall
    '';
  };
  registrationSetup = ''
    if [ -z "''${CAVEMAN_REGISTRATION_ROOT:-}" ]; then
      ${lib.optionalString (registrationProfile != null) ''
        export CAVEMAN_REGISTRATION_ROOT=${lib.escapeShellArg (toString registrationProfile)}
      ''}
      if [ -z "''${CAVEMAN_REGISTRATION_ROOT:-}" ]; then
        case "$0" in
          /*) registrationLauncher="$0" ;;
          *) registrationLauncher="$PWD/$0" ;;
        esac
        registrationRoot=""
        case "$registrationLauncher" in
          /nix/store/*) ;;
          */bin/*) registrationRoot="''${registrationLauncher%/bin/*}" ;;
          */lib/caveman/node|*/lib/caveman/bash)
            registrationRoot="''${registrationLauncher%/lib/caveman/*}"
            ;;
        esac
        if [ -n "$registrationRoot" ] \
          && [ -x "$registrationRoot/lib/caveman/node" ] \
          && [ -f "$registrationRoot/lib/caveman/dist/index.js" ]; then
          export CAVEMAN_REGISTRATION_ROOT="$registrationRoot"
        fi
      fi
    fi
  '';
in
stdenvNoCC.mkDerivation {
  pname = "caveman";
  inherit (pins) version;
  src = pins.cli;

  nativeBuildInputs = [ makeWrapper ];
  strictDeps = true;
  dontBuild = true;

  # Workaround: upstream has no package-manager-owned installation mode.
  # Remove when it can disable all executable installation and self-update paths.
  patches = [
    ../../../../patches/caveman-nix-managed-install.patch
    # Workaround: generated agent registrations retain runtime closure paths.
    # Remove when upstream separates execution from durable registration paths.
    ../../../../patches/caveman-nix-registration-paths.patch
    # Workaround: native Hermes wiring writes invalid YAML.
    # Remove when the CLI inserts a new section after the document start and
    # matches the siblings' list indentation.
    ../../../../patches/caveman-hermes-native-yaml.patch
  ];

  installPhase = ''
    runHook preInstall
    mkdir -p "$out/lib/caveman" "$out/bin" "$out/share/doc/caveman"
    cp -r dist package.json "$out/lib/caveman/"
    cp LICENSE NOTICE README.md "$out/share/doc/caveman/"
    ln -s ${installerSource} "$out/lib/caveman/source"
    for executable in ${runtime}/bin/*; do
      name="$(basename "$executable")"
      if [ "$name" != caveman-proxy ] && [ "$name" != caveman-blocks ]; then
        ln -s "$executable" "$out/bin/$name"
      fi
    done
    # Workaround: runtime tools resolve git and ps through their inherited PATH.
    # Remove when upstream accepts explicit dependency paths.
    # Keep runtime dependencies in the closure and registrations in the profile.
    launcherArgs=(
      --prefix PATH : "$out/bin:${
        lib.makeBinPath (
          [
            runtime
            git
            nodejs_22
          ]
          ++ lib.optionals stdenvNoCC.hostPlatform.isDarwin [ pkgs.darwin.ps ]
        )
      }"
      --set CAVEMAN_NIX_MANAGED 1
      --set-default DO_NOT_TRACK 1
      --set-default CAVEMAN_TELEMETRY 0
      --set CAVEMAN_PROXY_BIN "$out/bin/caveman-proxy"
      --set CAVEMAN_ENGINE_BIN ${runtime}/bin/caveman-engine
      --set CAVEMAN_MCP_BIN ${runtime}/bin/caveman-mcp
      --set CAVEMEM_BIN ${runtime}/bin/cavemem
      --set CAVEMAN_BROWSE_BIN ${runtime}/bin/caveman-browse
      --set CAVEMAN_SHRINK_BIN ${runtime}/bin/caveman-shrink
      --set CAVEMAN_BLOCKS_BIN ${runtime}/bin/caveman-blocks
      --run ${lib.escapeShellArg registrationSetup}
    )
    makeWrapper ${lib.getExe nodejs_22} "$out/bin/caveman" \
      "''${launcherArgs[@]}" --add-flags "$out/lib/caveman/dist/index.js"
    makeWrapper ${lib.getExe nodejs_22} "$out/bin/caveman-install" \
      "''${launcherArgs[@]}" --add-flags "${installerSource}/installer/install.js"
    makeWrapper ${lib.getExe nodejs_22} "$out/lib/caveman/node" "''${launcherArgs[@]}"
    makeWrapper ${lib.getExe bash} "$out/lib/caveman/bash" \
      "''${launcherArgs[@]}" --prefix PATH : ${
        lib.makeBinPath [
          pkgs.coreutils
          pkgs.gnugrep
          pkgs.gnused
        ]
      }
    makeWrapper ${runtime}/bin/caveman-proxy "$out/bin/caveman-proxy" "''${launcherArgs[@]}"
    makeWrapper ${runtime}/bin/caveman-blocks "$out/bin/caveman-blocks" "''${launcherArgs[@]}"
    ln -s caveman "$out/bin/cave"
    runHook postInstall
  '';

  passthru = {
    inherit runtime installerSource registrationProfile;
  };

  meta = {
    description = "Caveman CLI with its complete local compression, proxy, memory, browsing and Blocks runtime";
    homepage = "https://github.com/JuliusBrussee/caveman";
    license = lib.licenses.asl20;
    mainProgram = "caveman";
    sourceProvenance = [ lib.sourceTypes.binaryBytecode ];
    platforms = [
      "aarch64-darwin"
      "aarch64-linux"
      "x86_64-linux"
    ];
  };
}
