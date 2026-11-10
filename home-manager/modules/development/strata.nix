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
  mutableDirectory = lib.types.addCheck lib.types.str (
    path: lib.hasPrefix "/" path && !(path == "/nix/store" || lib.hasPrefix "/nix/store/" path)
  );
  strataPackage = pkgs.writeShellApplication {
    name = "strata";
    runtimeInputs = [
      pkgs.git
      pkgs.nix
    ];
    text = ''
      # Configured directory paths are literal arguments, not shell expansions.
      # shellcheck disable=SC2016
      exec nix develop --no-update-lock-file "path:${self}#strata" \
        --command python3 ${./strata-workspace.py} \
        ${lib.escapeShellArg cfg.workspaceDirectory} ${inputs.strata.rev} \
        ${lib.escapeShellArg (if cfg.dataDirectory == null then "" else cfg.dataDirectory)} \
        ${lib.escapeShellArg (if cfg.modelsDirectory == null then "" else cfg.modelsDirectory)} "$@"
    '';
  };
in
{
  options.modules.development.strata = {
    enable = lib.mkEnableOption "Strata using its upstream Nix development environment";
    workspaceDirectory = lib.mkOption {
      type = mutableDirectory;
      default = "${config.xdg.dataHome}/strata";
      defaultText = lib.literalExpression ''"''${config.xdg.dataHome}/strata"'';
      description = ''
        Absolute writable directory outside /nix/store for the source checkout, virtual
        environment, engines, build caches and interpreter GC root. Contents remain
        user-owned and are not copied into the Nix store. Changing this path does not
        migrate an existing workspace.
      '';
    };
    dataDirectory = lib.mkOption {
      type = lib.types.nullOr mutableDirectory;
      default = null;
      description = ''
        Optional absolute directory outside /nix/store for new models, packs and drafts
        during first bootstrap or explicit setup. Null leaves upstream folder selection unchanged.
        An explicit CLI --data-dir takes priority. Normal installed launches, updates,
        checks and standalone commands do not receive this default. Existing models are
        not migrated by this option; upstream retains its explicit move confirmation.
        Model selection, tuning and profiles remain owned by the upstream wizard.
      '';
    };
    modelsDirectory = lib.mkOption {
      type = lib.types.nullOr mutableDirectory;
      default = null;
      description = ''
        Optional absolute directory outside /nix/store passed as --models-dir during
        first bootstrap or explicit setup. Overrides the upstream GGUF download folder
        without changing the data directory used for packs and drafts. Null leaves
        upstream selection unchanged, normally <data directory>/models. An explicit
        CLI --models-dir takes priority, including supported abbreviations and equals
        syntax. Normal installed launches, updates, checks and standalone commands do
        not receive this default. Existing files are not migrated; the upstream wizard
        retains model selection, tuning and profiles.
      '';
    };
    package = lib.mkOption {
      type = lib.types.package;
      default = strataPackage;
      defaultText = lib.literalExpression "strataPackage";
      description = "Strata launcher using the upstream x86_64-linux CUDA development environment";
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
