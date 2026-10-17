{
  lib,
  stdenvNoCC,
  makeWrapper,
  python3,
  git,
  chromium,
  google-chrome,
  pins,
}:

let
  platforms = {
    aarch64-darwin = "darwin_arm64";
    aarch64-linux = "linux_arm64";
    x86_64-linux = "linux_amd64";
  };
  platform =
    platforms.${stdenvNoCC.hostPlatform.system}
      or (throw "Caveman runtime is unsupported on ${stdenvNoCC.hostPlatform.system}");
  binaries = pins.runtime.${platform};
  browserExecutable =
    if stdenvNoCC.hostPlatform.isDarwin then
      "${google-chrome}/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    else
      lib.getExe chromium;
in
stdenvNoCC.mkDerivation {
  pname = "caveman-runtime";
  inherit (pins) version;

  dontUnpack = true;
  dontStrip = true;
  nativeBuildInputs = [ makeWrapper ];

  installPhase = ''
    runHook preInstall
    mkdir -p "$out/bin" "$out/share/licenses/caveman-runtime"
    ${lib.concatStringsSep "\n" (
      lib.mapAttrsToList (name: binary: ''
        install -m755 ${binary} "$out/bin/${name}"
      '') binaries
    )}
    for name in LICENSE LICENSE-MIT LICENSING.md NOTICE; do
      install -m644 "${pins.src}/$name" "$out/share/licenses/caveman-runtime/$name"
    done
    ${lib.concatStringsSep "\n" (
      lib.mapAttrsToList (name: license: ''
        install -m644 ${license} "$out/share/licenses/caveman-runtime/${name}"
      '') pins.licenses
    )}
    wrapProgram "$out/bin/caveman-proxy" \
      --prefix PATH : ${lib.makeBinPath [ git ]}
    # Blocks executes Python scripts, checking for Python >= 3.10 on PATH.
    wrapProgram "$out/bin/caveman-blocks" \
      --prefix PATH : ${
        lib.makeBinPath [
          python3
          git
        ]
      } \
      --set-default DO_NOT_TRACK 1 \
      --set-default CAVEMAN_TELEMETRY 0
    # Keep an explicit user override; browsing uses a Nix-managed browser.
    wrapProgram "$out/bin/caveman-browse" \
      --set-default CAVEMAN_BROWSE_CHROME ${lib.escapeShellArg browserExecutable}
    runHook postInstall
  '';

  meta = {
    description = "Pinned Caveman companion binaries with native runtime dependencies";
    homepage = "https://github.com/JuliusBrussee/caveman";
    license = with lib.licenses; [
      asl20
      mit
    ];
    platforms = builtins.attrNames platforms;
    sourceProvenance = [ lib.sourceTypes.binaryNativeCode ];
  };
}
