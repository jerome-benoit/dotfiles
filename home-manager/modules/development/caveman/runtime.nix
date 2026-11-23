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
  src,
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
  version = pins.runtimeVersion;

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
      install -m644 "${src}/$name" "$out/share/licenses/caveman-runtime/$name"
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
    # Workaround: the prebuilt companion can discover Hermes independently of the CLI.
    # Remove only when the pinned companion requires explicit JSON config and
    # refuses automatic discovery even with a config, or safely discovers Hermes
    # servers without bypassing MCP filters or mutating Hermes configuration.
    wrapProgram "$out/bin/caveman-mcp" --run ${lib.escapeShellArg ''
      if [[ ''${1-} == codemode ]]; then
        (
          shift
          config=
          discover=0
          # Match the pinned companion's Go flag parsing: stop at a positional argument.
          while [[ ''${1-} == -?* && $1 != -- ]]; do
            flag=''${1#-}
            flag=''${flag#-}
            shift
            case "$flag" in
              h|help|h=*|help=*)
                cat >&2 <<'EOF'
      Usage: caveman-mcp codemode --config PATH [OPTIONS]

        --config PATH             JSON MCP server configuration (required)
        --workspace PATH          Workspace root (default: current directory)
        --no-builtins             Disable built-in repo, PR, and browse tools
        --no-js                   Disable JavaScript; use pipeline steps only
        --allow-writes-in-execute Allow mutating tools in codemode_execute
        -h, --help                Show this help

      Automatic MCP discovery is disabled.
      EOF
                exit 64
                ;;
              config|workspace)
                if [[ $# -eq 0 ]]; then
                  printf 'caveman-mcp codemode: --%s requires a value\n' "$flag" >&2
                  exit 2
                fi
                flag+="=$1"
                shift
                ;;
            esac
            case "$flag" in
              config=*) config=''${flag#*=} ;;
              discover|discover=1|discover=t|discover=T|discover=true|discover=TRUE|discover=True) discover=1 ;;
              discover=0|discover=f|discover=F|discover=false|discover=FALSE|discover=False) discover=0 ;;
              workspace=*|trust-workspace|trust-workspace=*|no-builtins|no-builtins=*|\
              no-js|no-js=*|allow-writes-in-execute|allow-writes-in-execute=*) ;;
              discover=*)
                printf 'caveman-mcp codemode: invalid boolean for --discover: %s\n' "''${flag#*=}" >&2
                exit 2
                ;;
              *)
                printf 'caveman-mcp codemode: unknown option: %s\n' "$flag" >&2
                exit 2
                ;;
            esac
          done
          if [[ $discover != 0 ]]; then
            printf '%s\n' 'caveman-mcp codemode: automatic discovery (--discover) is disabled' >&2
            exit 2
          fi
          if [[ -z $config ]]; then
            printf '%s\n' 'caveman-mcp codemode: --config PATH is required' >&2
            exit 2
          fi
        ) || case $? in
          64) exit 0 ;; # Help was handled by the wrapper.
          *) exit 2 ;;
        esac
      fi
    ''}
    runHook postInstall
  '';

  passthru = { inherit browserExecutable; };

  meta = {
    description = "Pinned Caveman companion binaries and source-built Blocks with native runtime dependencies";
    homepage = "https://github.com/JuliusBrussee/caveman";
    license = with lib.licenses; [
      asl20
      mit
    ];
    platforms = builtins.attrNames platforms;
    sourceProvenance = with lib.sourceTypes; [
      fromSource
      binaryNativeCode
    ];
  };
}
