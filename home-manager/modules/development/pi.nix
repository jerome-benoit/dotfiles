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
    version = "0.75.1";

    src = pkgs.fetchzip {
      url = "https://registry.npmjs.org/@earendil-works/pi-coding-agent/-/pi-coding-agent-${finalAttrs.version}.tgz";
      hash = "sha256-vevduMD9U7yAnfpLqrsl0FnnUdA2ZE7US2HwCIbh+nQ=";
    };

    npmDepsHash = "sha256-5Pwnc3BqoVymwkhalVgCVdtVN733bmpKAdrkJfqDhJ4=";

    postPatch = ''
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
