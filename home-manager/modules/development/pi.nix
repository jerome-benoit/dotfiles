{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.development.pi;

  piPackage = pkgs.buildNpmPackage (finalAttrs: {
    pname = "pi-coding-agent";
    # renovate: datasource=npm depName=@earendil-works/pi-coding-agent
    version = "0.79.9";

    src = pkgs.fetchzip {
      url = "https://registry.npmjs.org/@earendil-works/pi-coding-agent/-/pi-coding-agent-${finalAttrs.version}.tgz";
      hash = "sha256-A0uNRK0v+ajLaZwaPNLEcnSwbqfDE24OeMvIDBYeFac="; # @ci:src-hash
    };

    npmDeps = pkgs.fetchNpmDeps {
      name = "${finalAttrs.pname}-${finalAttrs.version}-npm-deps";
      unpackPhase = "true";
      postPatch = ''
        cp ${./pi-package-lock.json} package-lock.json
      '';
      hash = "sha256-JYJDbqMi+J6JKJGZGHJ6a8k5gwZFrIAo5vRsCxVHvjE="; # @ci:npm-deps-hash
    };

    postPatch = ''
      rm -f npm-shrinkwrap.json
      cp ${./pi-package-lock.json} package-lock.json
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
