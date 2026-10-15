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
      pkgs.git
      pkgs.nix
    ];
    text = ''
      stateDir="''${XDG_DATA_HOME:-$HOME/.local/share}/strata"
      exec nix develop --no-update-lock-file "path:${self}#strata" \
        --command python3 ${./strata-workspace.py} "$stateDir" ${inputs.strata.rev} "$@"
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
        On invocation it enters the development shell and maintains a persistent
        Git checkout under XDG_DATA_HOME (defaulting to ~/.local/share). Source
        revisions are fetched from GitHub and checked out at the locked commit;
        configuration and runtime files remain in the same working directory.
        Existing revision-specific installations are adopted in place.
        All supplied arguments are forwarded to upstream setup.sh.
        After a source change, upstream update mode refreshes all installed
        configurations and dependencies before the requested command runs.
        The updater and server processes retain the workspace lock for their
        lifetime; the server replaces setup.py so signals reach it directly.
        Upstream manages the virtual environment, engine, model downloads and
        remembered data directory. Home Manager activation does not run the installer.
        A virtual environment whose Python interpreter or pip is unusable is
        recreated after entering the development shell, and its runtime marker
        is invalidated so upstream update mode restores dependencies. Source,
        configuration and model data are preserved.
        Failed repairs remain pending across launches until upstream update
        succeeds; preparing an existing checkout does not validate its runtime.
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
