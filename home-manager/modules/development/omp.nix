{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.development.omp;
  stdenv = pkgs.stdenvNoCC;
  hp = stdenv.hostPlatform;
  pins =
    (import ./pins {
      inherit lib;
      inherit (pkgs) fetchurl fetchzip;
    }).omp;

  # hp.node.{platform,arch} yields the upstream asset names (linux-x64, linux-arm64, darwin-arm64).
  platformKey = "${hp.node.platform}-${hp.node.arch}";

  version = pins.version;

  # ONNX addons' RUNPATH does not include the C++ runtime.
  # Supply autoPatchelfHook's baseline and the Linux workers' library path.
  nativeLibraries =
    lib.optionals hp.isElf [
      pkgs.stdenv.cc.cc.lib
    ]
    ++ lib.optionals hp.isLinux [
      pkgs.stdenv.cc.cc.libgcc
    ];

  ompPackage =
    if !(pins.sources ? ${platformKey}) then
      null
    else
      stdenv.mkDerivation {
        pname = "omp";
        inherit version;

        src = pins.sources.${platformKey};

        dontUnpack = true;
        dontBuild = true;
        # otherwise the bundled bun runtime is executed instead of the binary
        dontStrip = true;

        nativeBuildInputs = [
          pkgs.installShellFiles
          pkgs.makeBinaryWrapper
        ]
        ++ lib.optionals hp.isElf [ pkgs.autoPatchelfHook ];

        buildInputs = nativeLibraries;

        strictDeps = true;

        installPhase = ''
          runHook preInstall
          install -Dm755 $src $out/bin/omp
          wrapProgram $out/bin/omp \
            --prefix PATH : ${lib.makeBinPath [ pkgs.git ]} \
            ${lib.optionalString hp.isLinux ''
              --set-default OMP_NATIVE_LIBRARY_PATH ${lib.makeLibraryPath nativeLibraries}
            ''}
          runHook postInstall
        '';

        preFixup = lib.optionalString (stdenv.buildPlatform.canExecute stdenv.hostPlatform) ''
          installOmpCompletions() {
            local completionDir
            completionDir=$(mktemp -d)
            HOME="$completionDir" XDG_CACHE_HOME="$completionDir/cache" XDG_CONFIG_HOME="$completionDir/config" \
              $out/bin/omp completions bash > "$completionDir/omp.bash"
            HOME="$completionDir" XDG_CACHE_HOME="$completionDir/cache" XDG_CONFIG_HOME="$completionDir/config" \
              $out/bin/omp completions fish > "$completionDir/omp.fish"
            HOME="$completionDir" XDG_CACHE_HOME="$completionDir/cache" XDG_CONFIG_HOME="$completionDir/config" \
              $out/bin/omp completions zsh > "$completionDir/omp.zsh"
            installShellCompletion --cmd omp \
              --bash "$completionDir/omp.bash" \
              --fish "$completionDir/omp.fish" \
              --zsh "$completionDir/omp.zsh"
          }
          postFixupHooks+=(installOmpCompletions)
        '';

        doInstallCheck = stdenv.buildPlatform.canExecute stdenv.hostPlatform;
        nativeInstallCheckInputs = [ pkgs.versionCheckHook ];
        versionCheckProgramArg = "--version";
        postInstallCheck = ''
          test -s $out/share/bash-completion/completions/omp.bash
          test -s $out/share/fish/vendor_completions.d/omp.fish
          test -s $out/share/zsh/site-functions/_omp
          ${lib.optionalString hp.isLinux ''
            # Load both runtimes through the library path provided by the wrapper.
            env -u LD_LIBRARY_PATH -u OMP_NATIVE_LIBRARY_PATH BUN_BE_BUN=1 "$out/bin/omp" -e '
              const { dlopen } = require("bun:ffi");
              const dirs = (process.env.OMP_NATIVE_LIBRARY_PATH || "").split(":").filter(Boolean);
              const libraries = {
                "libstdc++.so.6": { __cxa_demangle: { args: ["ptr", "ptr", "ptr", "ptr"], returns: "ptr" } },
                "libgcc_s.so.1": { _Unwind_Backtrace: { args: ["ptr", "ptr"], returns: "i32" } },
              };
              for (const [name, symbols] of Object.entries(libraries)) {
                const loaded = dirs.some(dir => {
                  try {
                    dlopen(dir + "/" + name, symbols).close();
                    return true;
                  } catch {
                    return false;
                  }
                });
                if (!loaded) {
                  console.error("unresolved: " + name);
                  process.exit(1);
                }
              }
            '
          ''}
        '';
        meta = {
          description = "oh-my-pi (omp) coding agent CLI";
          homepage = "https://omp.sh";
          license = lib.licenses.mit;
          mainProgram = "omp";
          sourceProvenance = with lib.sourceTypes; [ binaryNativeCode ];
          platforms = [
            "aarch64-darwin"
            "aarch64-linux"
            "x86_64-linux"
          ];
        };
      };
  optionalPackages = config.modules.core.lib.mkOptionalPackages [
    {
      package = cfg.package;
      warning = "omp: no prebuilt binary for system ${hp.system}";
    }
  ];
in
{
  options.modules.development.omp = {
    enable = lib.mkEnableOption "omp (oh-my-pi) coding agent";

    package = config.modules.core.lib.mkOptionalPackageOption {
      default = ompPackage;
      defaultText = lib.literalExpression "prebuilt omp release binary for the host platform";
      description = "omp coding agent package (null on unsupported systems)";
    };
  };

  config = lib.mkIf cfg.enable {
    home.packages = optionalPackages.packages;
    warnings = optionalPackages.warnings;
  };
}
