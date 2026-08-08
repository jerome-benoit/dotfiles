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

  # hp.node.{platform,arch} yields the upstream asset names (linux-x64, linux-arm64, darwin-arm64).
  platformKey = "${hp.node.platform}-${hp.node.arch}";

  # renovate: datasource=github-releases depName=can1357/oh-my-pi
  version = "17.2.11";

  hashes = {
    "linux-x64" = "sha256-uGTV7FkTN2G5Wzh60oN3pU2lRZtaqn5aNOgrBZU1C6M="; # @ci:src-hash-linux-x64
    "linux-arm64" = "sha256-OlNJvWz+ixxfQo6hCv7vlHMMeSOi5K5LljdivZQVG24="; # @ci:src-hash-linux-arm64
    "darwin-arm64" = "sha256-ME61Cpl0+bHdTXDNr67be/5evhaq2Rmm/XWpXmvTHuI="; # @ci:src-hash-darwin-arm64
  };

  ompPackage =
    if !(hashes ? ${platformKey}) then
      null
    else
      stdenv.mkDerivation (finalAttrs: {
        pname = "omp";
        inherit version;

        src = pkgs.fetchurl {
          url = "https://github.com/can1357/oh-my-pi/releases/download/v${finalAttrs.version}/omp-${platformKey}";
          hash = hashes.${platformKey};
        };

        dontUnpack = true;
        dontBuild = true;
        # otherwise the bundled bun runtime is executed instead of the binary
        dontStrip = true;

        nativeBuildInputs = [
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

        doInstallCheck = true;
        nativeInstallCheckInputs = [ pkgs.versionCheckHook ];
        versionCheckProgramArg = "--version";

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
      });
in
{
  options.modules.development.omp = {
    enable = lib.mkEnableOption "omp (oh-my-pi) coding agent";

    package = lib.mkOption {
      type = lib.types.nullOr lib.types.package;
      default = ompPackage;
      defaultText = lib.literalExpression "prebuilt omp release binary for the host platform";
      description = "omp coding agent package (null on unsupported systems)";
    };
  };

  config = lib.mkIf cfg.enable {
    home.packages = lib.optional (cfg.package != null) cfg.package;
    warnings = lib.optional (cfg.package == null) "omp: no prebuilt binary for system ${hp.system}";
  };
}
