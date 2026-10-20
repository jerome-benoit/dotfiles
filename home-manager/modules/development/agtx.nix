{
  config,
  lib,
  pkgs,
  inputs,
  ...
}:

let
  cfg = config.modules.development.agtx;

  agtxPackage = pkgs.rustPlatform.buildRustPackage {
    pname = "agtx";
    version = config.modules.core.lib.mkUnstableVersion inputs.agtx;
    src = inputs.agtx;

    cargoLock.lockFile = "${inputs.agtx}/Cargo.lock";

    nativeBuildInputs = [
      pkgs.makeWrapper
    ];

    nativeCheckInputs = lib.optionals pkgs.stdenv.hostPlatform.isLinux [
      pkgs.git
      pkgs.procps
    ];

    # Workaround: upstream test helpers need the test-mocks feature, absent by default.
    # Remove when the tests build without the extra feature.
    checkFeatures = [ "test-mocks" ];
    # Workaround: the test suite drives the git binary, and is unvalidated on Darwin.
    # Remove when the test suite passes on aarch64-darwin.
    doCheck = pkgs.stdenv.hostPlatform.isLinux;

    postFixup = ''
      wrapProgram $out/bin/agtx \
        --prefix PATH : ${
          lib.makeBinPath [
            pkgs.tmux
            pkgs.git
            pkgs.gh
          ]
        }
    '';

    meta = {
      description = "Terminal-native kanban board for managing coding agents";
      homepage = "https://github.com/fynnfluegge/agtx";
      license = lib.licenses.asl20;
      mainProgram = "agtx";
      platforms = lib.platforms.unix;
    };
  };
in
{
  options.modules.development.agtx = {
    enable = lib.mkEnableOption "agtx configuration";

    package = lib.mkOption {
      type = lib.types.package;
      default = agtxPackage;
      defaultText = lib.literalExpression "pkgs.rustPlatform.buildRustPackage { pname = \"agtx\"; ... }";
      description = "agtx package";
    };
  };

  config = lib.mkIf cfg.enable {
    home.packages = [ cfg.package ];
  };
}
