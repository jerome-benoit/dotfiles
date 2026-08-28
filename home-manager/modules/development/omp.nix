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

        # libstdc++/libgcc baseline for the bundled N-API addon; autoPatchelfHook flags any gap.
        buildInputs = lib.optionals hp.isElf [ pkgs.stdenv.cc.cc.lib ];

        strictDeps = true;

        installPhase = ''
          runHook preInstall
          install -Dm755 $src $out/bin/omp
          wrapProgram $out/bin/omp \
            --prefix PATH : ${lib.makeBinPath [ pkgs.git ]}
          runHook postInstall
        '';

        # The binary must be patched before it can generate its completion scripts.
        dontAutoPatchelf = stdenv.buildPlatform.canExecute stdenv.hostPlatform;
        preFixup = lib.optionalString (stdenv.buildPlatform.canExecute stdenv.hostPlatform) ''
          autoPatchelf "$out"
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
        '';

        doInstallCheck = stdenv.buildPlatform.canExecute stdenv.hostPlatform;
        nativeInstallCheckInputs = [ pkgs.versionCheckHook ];
        versionCheckProgramArg = "--version";
        postInstallCheck = ''
          test -s $out/share/bash-completion/completions/omp.bash
          test -s $out/share/fish/vendor_completions.d/omp.fish
          test -s $out/share/zsh/site-functions/_omp
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
