{
  lib,
  stdenvNoCC,
  fetchurl,
  fetchzip,
  nodejs_22,
  makeWrapper,
  git,
  callPackage,
}:
let
  pins = (import ../pins { inherit lib fetchurl fetchzip; }).caveman;
  runtime = callPackage ./runtime.nix { inherit pins; };
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
  patches = [ ../../../../patches/caveman-nix-managed-install.patch ];

  installPhase = ''
    runHook preInstall
    mkdir -p "$out/lib/caveman" "$out/bin" "$out/share/doc/caveman"
    cp -r dist package.json "$out/lib/caveman/"
    cp LICENSE NOTICE README.md "$out/share/doc/caveman/"
    for executable in ${runtime}/bin/*; do
      ln -s "$executable" "$out/bin/$(basename "$executable")"
    done
    makeWrapper ${lib.getExe nodejs_22} "$out/bin/caveman" \
      --add-flags "$out/lib/caveman/dist/index.js" \
      --prefix PATH : ${
        lib.makeBinPath [
          runtime
          git
          nodejs_22
        ]
      } \
      --set CAVEMAN_NIX_MANAGED 1 \
      --set-default DO_NOT_TRACK 1 \
      --set-default CAVEMAN_TELEMETRY 0 \
      --set CAVEMAN_PROXY_BIN ${runtime}/bin/caveman-proxy \
      --set CAVEMAN_ENGINE_BIN ${runtime}/bin/caveman-engine \
      --set CAVEMAN_MCP_BIN ${runtime}/bin/caveman-mcp \
      --set CAVEMEM_BIN ${runtime}/bin/cavemem \
      --set CAVEMAN_BROWSE_BIN ${runtime}/bin/caveman-browse \
      --set CAVEMAN_SHRINK_BIN ${runtime}/bin/caveman-shrink \
      --set CAVEMAN_BLOCKS_BIN ${runtime}/bin/caveman-blocks
    ln -s caveman "$out/bin/cave"
    runHook postInstall
  '';

  passthru = { inherit runtime; };

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
