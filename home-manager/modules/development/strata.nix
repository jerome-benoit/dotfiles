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
  # Workaround: upstream stores packs, QAD drafts and image VAE in the GGUF directory.
  # Remove when upstream supports separate GGUF and auxiliary directories.
  sourcePatch = ../../../patches/strata-setup-directory-roles.patch;
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
        ${lib.escapeShellArg (if cfg.modelsDirectory == null then "" else cfg.modelsDirectory)} \
        ${sourcePatch} "$@"
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
        environment, engines, build caches and interpreter GC root. The launcher applies
        its source patch under the workspace lock, leaves the diff visible and refuses
        conflicting edits. Other contents remain user-owned and outside the Nix store.
        Changing this path does not migrate the workspace.
      '';
    };
    dataDirectory = lib.mkOption {
      type = lib.types.nullOr mutableDirectory;
      default = null;
      description = ''
        Optional absolute directory outside /nix/store, passed as --data-dir for new
        models, packs and drafts during initial or explicit setup. Null preserves
        upstream folder selection; an explicit CLI --data-dir takes priority.
        Installed launches, updates, checks and standalone commands do not receive this
        default, and neither does any Terminal subcommand: their folders are in the model's run
        configuration. Existing models are not moved. Upstream retains explicit move
        confirmation and owns model selection, tuning and profiles.
      '';
    };
    modelsDirectory = lib.mkOption {
      type = lib.types.nullOr mutableDirectory;
      default = null;
      description = ''
        Optional absolute directory outside /nix/store, passed as --models-dir during
        initial or explicit setup. GGUF downloads and QAD dense/PLE outputs use
        this directory; NVFP4 packs, QAD checkpoints/drafts and image VAE files use the
        data directory.

        Complete NVFP4 installations are reused in place before selecting a QAD
        checkpoint. Fully verified checkpoints take priority over partial downloads.
        Checkpoints resume in place; new outputs use the selected GGUF and data directories.

        Null preserves upstream layout, normally <data directory>/models, including
        when --models-dir is supplied on the CLI. Explicit CLI values take priority,
        including supported abbreviations and equals syntax. Installed launches,
        updates, checks and standalone commands do not receive this default, nor does
        any Terminal subcommand.
        Existing files are not moved; the upstream wizard retains model selection,
        tuning and profiles.
      '';
    };
    package = lib.mkOption {
      type = lib.types.package;
      default = strataPackage;
      defaultText = lib.literalExpression "strataPackage";
      description = "Strata's one command in the upstream x86_64-linux CUDA development environment: a subcommand
        (launch, serve, status, monitor, update, doctor, ...) runs upstream's Terminal, and options or nothing run
        upstream's setup. --version is the Terminal's; --help stays upstream's setup help, because both programs
        declare it. The shape of the arguments decides, and both shapes are read from the pinned checkout, so a new
        upstream subcommand needs no change here. If upstream ever makes its setup ambiguous, the command says so
        instead of guessing which program was meant.";
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
