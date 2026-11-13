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
  # Workaround: upstream mixes GGUF/artifact directories and has no managed workspace lock lifecycle.
  # Remove when upstream separates destinations and locks acquisition and monitor updates without locking services.
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
        Managed setup, install, launch acquisition and other mutating Terminal commands
        hold this lock; mutating children inherit it, including Intel SYCL setup.
        Serving and monitoring release it after preparation. Both launch monitoring and
        standalone monitor reacquire a fresh lock for opt-in updates through model restart;
        a busy workspace refuses that update without blocking observation.
        Status, monitor, logs and connection bypass preparation only when the complete
        published source patch is applied and HEAD is valid, so they remain usable during
        acquisition and serving. Interrupted initialization and patch publication resume
        under the lock before the launcher imports its parser.
        A real launch or serve after a source pin change refreshes and validates installed runtimes
        before running the requested action. Failure leaves refresh pending for the next attempt.
        Direct upstream scripts outside this launcher do not participate in this lock.
        Changing this path does not migrate the workspace.
      '';
    };
    dataDirectory = lib.mkOption {
      type = lib.types.nullOr mutableDirectory;
      default = null;
      description = ''
        Optional absolute directory outside /nix/store, used as --data-dir for new
        models, packs and drafts during managed source setup, install and launch acquisition.
        External acquisitions keep upstream folder selection.
        Null preserves upstream folder selection; an explicit CLI --data-dir takes priority.
        This default is not a remembered CLI choice and does not request a data move.
        Installed starts, updates, checks and standalone commands keep their existing paths.
        Existing models are not moved. Upstream retains explicit move
        confirmation and owns model selection, tuning and profiles.
      '';
    };
    modelsDirectory = lib.mkOption {
      type = lib.types.nullOr mutableDirectory;
      default = null;
      description = ''
        Optional absolute directory outside /nix/store, passed as --models-dir during
        initial or explicit managed setup and launch acquisition.
        External acquisitions keep upstream folder selection.
        GGUF downloads and QAD dense/PLE outputs use this directory; NVFP4 packs,
        QAD checkpoints/drafts and image VAE files use the data directory.

        Complete NVFP4 installations are reused in place before selecting a QAD
        checkpoint. Fully verified checkpoints take priority over partial downloads.
        Checkpoints resume in place; new outputs use the selected GGUF and data directories.

        Null preserves upstream layout, normally <data directory>/models, including
        when --models-dir is supplied on the CLI. Explicit CLI values take priority,
        including supported abbreviations and equals syntax. Installed starts,
        updates, checks and standalone commands keep their existing paths.
        Managed acquisition through the launch runner receives these same defaults.
        Existing files are not moved; upstream retains model selection, tuning and profiles.
      '';
    };
    package = lib.mkOption {
      type = lib.types.package;
      default = strataPackage;
      defaultText = lib.literalExpression "strataPackage";
      description = ''
        Strata's public Terminal command in the upstream x86_64-linux CUDA development environment.
        Root help, version, bare usage and errors use the pinned Terminal parser.
        The source subcommand passes raw arguments to source setup: source --help shows setup help,
        source starts or calibrates installed models without forcing setup, and source --update
        explicitly refreshes the pinned source runtime. Install forces setup or --update as requested.
        Install help before a user-supplied -- separator stays in the Terminal parser,
        including after setup flags, and never starts an external installer's bootstrap.
        Update remains the upstream engine/Control feed command; it does not change the Nix source pin.
        A real launch, serve, install or cold monitor UI can bootstrap Python without installing a model.
        Interactive monitoring probes its UI imports in the selected runtime and resumes incomplete bootstrap.
        Help, including signed-feed family help in either argument order, does not discover feeds.
        Help, version, status, monitor --once and plans do not acquire Python packages, models or engines.
        Source and Nix environment realization can still require network access.
        A cold serve plan reports upstream's typed missing-dependency error until runtime is available.
        New source pins refresh installed runtimes automatically before real launch or serve.
        Managed launch configs share the source workspace. Source-built engines stay there;
        component engines keep upstream's shared store and explicit pins. Model data is reused
        in place. Explicit external launch targets keep upstream directory and runtime selection.
        External install targets use their own installer and runtime without private workspace state.
        Canonical aliases of the managed checkout retain managed setup and locking.
        Terminal commands preserve caller arguments and working directory, including relative config paths.
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
