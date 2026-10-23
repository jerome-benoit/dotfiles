{
  lib,
  pkgs,
  stdenvNoCC,
  makeWrapper,
  callPackage,
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
  blocks = callPackage ./blocks.nix { pins = pins.blocks; };
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
    ln -s ${blocks}/bin/caveman-blocks "$out/bin/caveman-blocks"
    for name in LICENSE LICENSE-MIT LICENSING.md NOTICE; do
      install -m644 "${pins.src}/$name" "$out/share/licenses/caveman-runtime/$name"
    done
    ${lib.concatStringsSep "\n" (
      lib.mapAttrsToList (name: license: ''
        install -m644 ${license} "$out/share/licenses/caveman-runtime/${name}"
      '') pins.licenses
    )}
    # Workaround: upstream resolves git and ps from PATH at run time; macOS
    # ships ps in /bin, outside a Nix-built PATH.
    # Remove when upstream takes those paths from its own configuration.
    wrapProgram "$out/bin/caveman-proxy" \
      --prefix PATH : "$out/bin:${
        lib.makeBinPath ([ git ] ++ lib.optionals stdenvNoCC.hostPlatform.isDarwin [ pkgs.darwin.ps ])
      }"
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
