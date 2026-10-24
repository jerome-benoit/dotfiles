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
    # Workaround: standalone installers persist their generation-specific Node.
    # Remove when upstream supports package-manager-owned registration paths.
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
          */share/caveman/node|*/share/caveman/bash)
            registrationRoot="''${registrationLauncher%/share/caveman/*}"
            ;;
        esac
        if [ -n "$registrationRoot" ] \
          && [ -x "$registrationRoot/share/caveman/node" ] \
          && [ -f "$registrationRoot/share/caveman/dist/index.js" ]; then
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
  ];

  installPhase = ''
    runHook preInstall
    mkdir -p "$out/lib/caveman" "$out/bin" "$out/share/doc/caveman" "$out/share/caveman"
    cp -r dist package.json "$out/lib/caveman/"
    cp LICENSE NOTICE README.md "$out/share/doc/caveman/"
    ln -s "$out/lib/caveman/dist" "$out/share/caveman/dist"
    ln -s ${installerSource} "$out/share/caveman/source"
    for executable in ${runtime}/bin/*; do
      name="$(basename "$executable")"
      if [ "$name" != caveman-proxy ] && [ "$name" != caveman-blocks ]; then
        ln -s "$executable" "$out/bin/$name"
      fi
    done
    # Workaround: upstream resolves git from PATH at run time, and the agent
    # runs the commands whose output it captures, ps among them, so ps has to
    # be on the PATH the agent inherits.
    # Remove when upstream takes those paths from its own configuration.
    # Runtime paths stay in the closure; serializers use the selected profile.
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
    makeWrapper ${lib.getExe nodejs_22} "$out/share/caveman/node" "''${launcherArgs[@]}"
    makeWrapper ${lib.getExe bash} "$out/share/caveman/bash" \
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
