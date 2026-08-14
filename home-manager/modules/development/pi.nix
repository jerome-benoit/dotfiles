{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.development.pi;
  pins =
    (import ./pins {
      inherit lib;
      inherit (pkgs) fetchurl fetchzip;
    }).pi;

  piPackage = pkgs.buildNpmPackage (finalAttrs: {
    pname = "pi-coding-agent";
    version = pins.version;
    src = pins.src;
    passthru = {
      contractLockFile = pins.lockFile;
      contractLockStorePath = "${pins.lockFile}";
    };

    npmDeps = pkgs.fetchNpmDeps {
      name = "${finalAttrs.pname}-${finalAttrs.version}-npm-deps";
      unpackPhase = "true";
      postPatch = ''
        cp ${pins.lockFile} package-lock.json
      '';
      hash = pins.npmDepsHash;
    };

    postPatch = ''
      rm -f npm-shrinkwrap.json
      cp ${pins.lockFile} package-lock.json
    '';

    dontNpmBuild = true;

    npmFlags = [
      "--no-audit"
      "--no-fund"
      "--ignore-scripts"
    ];

    meta = {
      description = "Agentic coding CLI";
      homepage = "https://github.com/earendil-works/pi";
      license = lib.licenses.mit;
      mainProgram = "pi";
      platforms = lib.platforms.unix;
      sourceProvenance = with lib.sourceTypes; [ binaryBytecode ];
    };
  });
in
{
  options.modules.development.pi = {
    enable = lib.mkEnableOption "pi coding agent configuration";

    package = lib.mkOption {
      type = lib.types.package;
      default = piPackage;
      defaultText = lib.literalExpression "buildNpmPackage from npm registry tarball";
      description = "pi coding agent package";
    };
  };

  config = lib.mkIf cfg.enable {
    home.packages = [ cfg.package ];
  };
}
