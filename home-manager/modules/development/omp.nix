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
  version = "17.3.4";

  hashes = {
    "linux-x64" = "sha256-P85LJWKAZLDNe/vGJF7NraMxdQ7Us0Gspr0pukR4qrU="; # @ci:src-hash-linux-x64
    "linux-arm64" = "sha256-jifnv+SfwPM/bLC1ASirhf5UAzMNHftbs0zx90Is3Og="; # @ci:src-hash-linux-arm64
    "darwin-arm64" = "sha256-dqbCL4ukujGePVKK3NkhlJ4DOPKxMEJyHmS5kPb//hY="; # @ci:src-hash-darwin-arm64
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
