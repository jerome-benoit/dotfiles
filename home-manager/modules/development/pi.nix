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
    # renovate: datasource=npm depName=@mariozechner/pi-coding-agent
    version = "0.67.68";

    src = pkgs.fetchzip {
      url = "https://registry.npmjs.org/@mariozechner/pi-coding-agent/-/pi-coding-agent-${finalAttrs.version}.tgz";
      hash = "sha256-e/+eAgReKUYCxPkhN/TD7zcryl4RwwSYtGHL4Fz2HQo=";
    };

    npmDepsHash = "sha256-4o17Wao//cG6btQbPuDgj0omkwpSPih2EiFkLezLTIs=";

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
      description = "Agentic coding CLI by Mario Zechner";
      homepage = "https://github.com/badlogic/pi-mono";
      downloadPage = "https://www.npmjs.com/package/@mariozechner/pi-coding-agent";
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
