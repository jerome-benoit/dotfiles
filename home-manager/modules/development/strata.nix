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
        Absolute writable directory outside /nix/store for the source checkout,
        Python environment, engines, build caches and interpreter GC root.
        The launcher keeps its source patch visible and refuses conflicting edits.

        Managed setup, updates and model acquisition serialize workspace mutations.
        Serving and observation release the mutation lock after preparation.
        Monitor updates refuse a busy workspace without blocking observation.
        Prepared same-pin stop commands remain available while an updater waits.
        Source publication protects command initialization; direct upstream scripts
        outside this launcher do not participate in these protections.

        Other workspace contents remain user-owned. Changing this path does not
        migrate the workspace.
      '';
    };
    dataDirectory = lib.mkOption {
      type = lib.types.nullOr mutableDirectory;
      default = null;
      description = ''
        Optional absolute directory outside /nix/store, used as --data-dir during
        managed source setup, install and launch acquisition.
        Null keeps upstream selection; explicit CLI values take priority.
        Independent external installations keep upstream directory selection.

        This default stays unsaved in launch settings and presets. The Folder screen
        preserves unchanged explicit choices, including choices equal to the default.
        This default does not request a move or redirect installed starts, updates,
        checks or standalone actions. Upstream retains explicit move confirmation.
      '';
    };
    modelsDirectory = lib.mkOption {
      type = lib.types.nullOr mutableDirectory;
      default = null;
      description = ''
        Optional absolute directory outside /nix/store, used as --models-dir during
        managed source setup, install and launch acquisition.
        GGUF downloads and QAD dense/PLE outputs use this directory; NVFP4 packs,
        QAD checkpoints/drafts and image VAE files use the data directory.
        Null leaves upstream selection unchanged, normally <data directory>/models.
        Explicit CLI paths take priority; independent external installations keep
        upstream directory selection.

        Complete retained files are reused in place. Missing files use the requested
        destinations, including vision projectors. Plans and progress follow native
        path selection and completion evidence. Launch progress retains acquisition
        sources when the saved data directory changes. DeepSeek checks remaining
        downloads per destination filesystem.
        This default does not request a move or redirect installed starts, updates,
        checks or standalone actions.
      '';
    };
    package = lib.mkOption {
      type = lib.types.package;
      default = strataPackage;
      defaultText = lib.literalExpression "strataPackage";
      description = ''
        Strata's Terminal CLI in the upstream x86_64-linux CUDA development environment.
        Bare strata prints native usage and exits 2; strata --help prints Terminal help
        and exits 0. Terminal dispatch preserves caller arguments and working directory,
        including relative config paths; native actions may select their own directories.

        strata source runs source setup from the managed checkout without forcing --setup.
        source --help shows setup help; source --update refreshes the pinned source runtime.
        strata install runs the selected installation's installer and runtime from its
        directory, forcing --setup or --update as requested. Native install also accepts
        setup options; these are not Terminal root options.
        strata update uses the signed engine/Control feed without changing the Nix source pin.

        After source-pin changes, real managed launch or serve refreshes source/Python
        automatically. Launch acquires missing components, then validates its selected
        config before tuning or starting. Unrelated incomplete installations do not block
        launch. Independent external runtimes keep upstream selection and skip workspace
        reconciliation; Terminal Python may still bootstrap.

        Real commands may bootstrap Python as needed. Help, version, status, monitor --once
        and plans do not bootstrap Python or acquire models or engines. Source preparation
        and Nix realization can still need network; a cold serve plan can report missing
        dependencies. Upstream owns model selection, explicit moves, tuning and profiles.
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
