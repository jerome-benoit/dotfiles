{
  config,
  lib,
  pkgs,
  inputs,
  self,
  ...
}:
let
  cfg = config.modules.development.strata;
  strataPackage = pkgs.writeShellApplication {
    name = "strata";
    runtimeInputs = [
      pkgs.coreutils
      pkgs.nix
    ];
    text = ''
      stateDir="''${XDG_DATA_HOME:-$HOME/.local/share}/strata"
      appDir="$stateDir/source-${inputs.strata.rev}"
      if [[ ! -d "$appDir" ]]; then
        mkdir -p -- "$stateDir"
        staging=$(mktemp -d "$stateDir/.source.XXXXXXXX")
        trap 'rm -rf -- "$staging"' EXIT
        cp -R ${inputs.strata}/. "$staging/"
        chmod -R u+w "$staging"
        mv --no-clobber --no-target-directory -- "$staging" "$appDir"
        rm -rf -- "$staging"
        trap - EXIT
      fi
      exec nix develop --no-update-lock-file "path:${self}#strata" \
        --command "$appDir/setup.sh" "$@"
    '';
  };
in
{
  options.modules.development.strata = {
    enable = lib.mkEnableOption "Strata using its upstream Nix development environment";
    package = lib.mkOption {
      type = lib.types.package;
      default = strataPackage;
      defaultText = lib.literalExpression "strataPackage";
      description = ''
        Launcher using Strata's pinned upstream x86_64-linux CUDA environment.
        On invocation it creates a writable, revision-specific source tree under
        XDG_DATA_HOME (defaulting to ~/.local/share), then runs upstream setup.sh
        with the supplied arguments. Upstream manages the virtual environment,
        engine, model downloads and remembered data directory. Home Manager
        activation does not run the installer.
      '';
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = pkgs.stdenv.hostPlatform.system == "x86_64-linux";
        message = "Strata's upstream flake only provides an x86_64-linux CUDA environment";
      }
    ];
    home.packages = [ cfg.package ];
  };
}
