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
        Serving and observers release acquisition ownership after preparation. Monitor
        updates acquire a fresh workspace lock through model restart; a busy workspace
        refuses that update without blocking observation.

        A separate publication lease protects source checks, native parsing, exec and
        consumer initialization. One-shot observers keep a read lease until completion;
        logs and monitors release it before polling. Services release it at native
        readiness after caching deferred helpers. Fetching does not hold the publication lock.
        Warm observations require the complete applied overlay and a valid HEAD.
        Interrupted initialization and publication resume before parser inspection.
        Managed launch and serve refresh and validate their runtimes after source pin
        changes; failed repairs remain pending. Independent external runtimes skip this
        reconciliation. Direct upstream scripts outside this launcher do not participate
        in these leases.
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
        Upstream retains explicit move
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
        Download progress uses setup's destinations and reuse selection, including
        retained checkpoints; vision projectors follow the requested model directory.
        These defaults do not request moves; upstream retains model selection, tuning and profiles.
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
        Real launch, serve, install, bench run and cold monitor UI commands can bootstrap
        Python without installing a model. Interactive monitoring checks its real UI consumer
        in the selected runtime and resumes incomplete bootstrap.
        Help, including signed-feed family help in either argument order, does not discover feeds.
        Help, version, status, monitor --once and plans do not acquire Python packages, models or engines.
        Source and Nix environment realization can still require network access.
        A cold serve plan reports upstream's typed missing-dependency error until runtime is available.
        New source pins refresh installed runtimes automatically before real managed launch or serve.
        Launch ownership follows the native catalog. Serve follows its canonical config
        or the original raw executable when that executable belongs to the workspace,
        independently of STRATA_INSTALL_DIR. Component references retain upstream pins.
        Independent external runtimes skip workspace reconciliation but may bootstrap Terminal Python.
        Installed base configs and source-built engines stay in the workspace. Derived
        launch configs remain in upstream's state directory and receive native argument
        migrations before serving, including when the runtime is already certified.
        Component engines keep upstream's shared store. Explicit external launch targets
        keep upstream directory and runtime selection.
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
