{
  config,
  inputs,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.development.hermesAgent;
  serviceCfg = config.services.hermes-agent;
  system = pkgs.stdenv.hostPlatform.system;
  isDarwin = pkgs.stdenv.hostPlatform.isDarwin;
  isLinux = pkgs.stdenv.hostPlatform.isLinux;
  configDir = serviceCfg.hermesHome;
  homePath = /. + config.home.homeDirectory;
  pluginHomePath = /. + configDir;
  pluginHomeIsValid =
    lib.hasPrefix "/" configDir
    && configDir == toString pluginHomePath
    && config.home.homeDirectory == toString homePath
    && lib.path.hasPrefix homePath pluginHomePath;

  hermesModuleCommon = import "${inputs.hermes-agent}/nix/moduleCommon.nix" {
    inherit lib;
  };
  baseHermesAgentPackage = inputs.hermes-agent.packages.${system}.default.override {
    inherit (pkgs) callPackage;
  };

  cudaRuntimeEnabled = isLinux && config.modules.core.gpu.acceleration == "cuda";
  cublasRuntimeEnabled = cudaRuntimeEnabled && pkgs.stdenv.hostPlatform.isx86_64;
  voiceRuntimeLibVar = if isDarwin then "DYLD_FALLBACK_LIBRARY_PATH" else "LD_LIBRARY_PATH";
  voiceRuntimeLibPath =
    lib.makeLibraryPath (
      [ pkgs.portaudio ]
      ++ lib.optionals cublasRuntimeEnabled [
        # Only the x86_64 CTranslate2 wheel uses CUDA; the aarch64 wheel uses OpenBLAS.
        # Its CUDA 12 ABI is independent of the selected CUDA package set.
        pkgs.cudaPackages_12_9.libcublas
      ]
    )
    # They also dlopen libcuda.so.1, so expose addDriverRunpath.driverLink.
    + lib.optionalString cudaRuntimeEnabled ":${pkgs.addDriverRunpath.driverLink}/lib";

  # Workaround: upstream wrappers omit PortAudio and CUDA runtime library paths.
  # Remove when upstream exposes those libraries to Hermes executables.
  hermesAgentPackage = baseHermesAgentPackage.overrideAttrs (previousAttrs: {
    postFixup = (previousAttrs.postFixup or "") + ''
      for bin in "$out"/bin/*; do
        [ -x "$bin" ] || continue
        wrapProgram "$bin" --prefix ${voiceRuntimeLibVar} : "${voiceRuntimeLibPath}"
      done
    '';
  });
  effectiveHermesAgentPackage = hermesModuleCommon.effectivePackage serviceCfg;
  hermesDesktopPackage = effectiveHermesAgentPackage.hermesDesktop or null;

  # Workaround: mkStateScript quotes mkdir but not the other state destinations.
  # Render safe shell-word placeholders, then quote the real roots exactly once.
  # Keep the actual working directory in config.yaml, not its shell placeholder.
  # Remove this adapter when upstream quotes every use of both destination roots.
  hermesStateScript =
    builtins.replaceStrings [ "__DOTFILES_HERMES_HOME__" "__DOTFILES_HERMES_WORKING_DIRECTORY__" ]
      (map lib.escapeShellArg [
        configDir
        serviceCfg.workingDirectory
      ])
      (
        hermesModuleCommon.mkStateScript {
          inherit pkgs;
          cfg = serviceCfg;
          hermesHome = "__DOTFILES_HERMES_HOME__";
          workingDirectory = "__DOTFILES_HERMES_WORKING_DIRECTORY__";
          configWorkingDirectory = serviceCfg.workingDirectory;
          run = "$DRY_RUN_CMD ";
          stateDirs = hermesModuleCommon.stateSubdirs;
          managedSystem = "home-manager";
          modes = {
            config = "0600";
            env = "0600";
            managed = "0600";
            auth = "0600";
            document = "0600";
          };
        }
      );

in
{
  options.modules.development.hermesAgent = {
    enable = lib.mkEnableOption "hermes-agent configuration";

    enableGateway = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Whether to run the Hermes Agent messaging gateway";
    };

    enableDashboard = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Whether to run the Hermes Agent web dashboard and desktop backend";
    };

    enableDesktop = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Whether to install the Hermes Agent desktop app";
    };

    desktopPackage = config.modules.core.lib.mkOptionalPackageOption {
      default = hermesDesktopPackage;
      defaultText = lib.literalExpression "hermesAgentPackage.hermesDesktop";
      description = "Hermes Agent desktop package";
    };

    plugins = lib.mkOption {
      type = lib.types.addCheck (lib.types.attrsOf lib.types.path) (
        plugins:
        lib.all (
          name:
          builtins.match "[A-Za-z0-9][A-Za-z0-9._-]*" name != null
          && name != "model-providers"
          && !(lib.hasPrefix "nix-managed-" name)
        ) (builtins.attrNames plugins)
      );
      default = { };
      description = ''
        Plugin source directories keyed by canonical name; each contains plugin.yaml and __init__.py.
        Non-empty plugins require normalized absolute home.homeDirectory and
        services.hermes-agent.hermesHome paths, with hermesHome equal to or below homeDirectory.
      '';
    };
  };

  # Workaround: upstream emits HERMES_HOME without systemd Environment quoting.
  # Adapt only its exact assignment; leave user additions and quoted entries intact.
  # Remove when upstream quotes processEnvironment values in its user units.
  options.systemd.user.services = lib.mkOption {
    type = lib.types.attrsOf (
      lib.types.submodule (
        { name, ... }: {
          options.Service.Environment = lib.mkOption {
            apply =
              entries:
              if
                cfg.enable
                && isLinux
                && lib.elem name [
                  "hermes-agent"
                  "hermes-backend"
                ]
              then
                map (
                  entry:
                  if entry == "HERMES_HOME=${configDir}" then
                    builtins.toJSON (lib.replaceStrings [ "%" ] [ "%%" ] entry)
                  else
                    entry
                ) entries
              else
                entries;
          };
        }
      )
    );
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = serviceCfg.environment == { } && serviceCfg.environmentFiles == [ ];
        message = ''
          Hermes Agent environment variables are managed by the sops-nix
          hermes-env secret; leave services.hermes-agent.environment and
          services.hermes-agent.environmentFiles empty.
        '';
      }
      {
        assertion = cfg.plugins == { } || pluginHomeIsValid;
        message = ''
          Hermes Agent declarative plugins require normalized absolute home.homeDirectory and
          services.hermes-agent.hermesHome paths, with hermesHome equal to or below homeDirectory.
          External Hermes homes are supported only when modules.development.hermesAgent.plugins is empty.
        '';
      }
    ];

    services.hermes-agent = {
      enable = true;
      package = lib.mkDefault hermesAgentPackage;
      gateway.enable = cfg.enableGateway;
      backend.mode = if cfg.enableDashboard then "dashboard" else "none";
    };

    systemd.user.services = lib.mkIf isLinux (
      lib.mkMerge [
        (lib.mkIf cfg.enableGateway {
          hermes-agent.Unit = {
            After = [ "sops-nix.service" ];
            Requires = [ "sops-nix.service" ];
          };
        })
        (lib.mkIf cfg.enableDashboard {
          hermes-backend.Unit = {
            After = [ "sops-nix.service" ];
            Requires = [ "sops-nix.service" ];
          };
        })
      ]
    );

    programs.hermes-agent = {
      enable = true;
    }
    // lib.optionalAttrs (cfg.enableDesktop && cfg.desktopPackage != null) {
      desktop = {
        enable = true;
        package = cfg.desktopPackage;
      };
    };

    home = {
      activation.hermesAgentSetup = lib.mkForce (
        lib.hm.dag.entryAfter [ "writeBoundary" "linkGeneration" ] hermesStateScript
      );

      # Workaround: upstream extraPlugins uses names its migration checks do not recognize.
      # Remove when upstream installs plugins under their canonical names.
      file = lib.mapAttrs' (
        name: source: lib.nameValuePair "${configDir}/plugins/${name}" { inherit source; }
      ) cfg.plugins;

      # The Linux link must exist before reloadSystemd can start new services.
      # Its target may still be absent: After/Requires=sops-nix gates service startup.
      # Darwin waits for synchronous sops activation before loading launchd agents.
      # Remove when upstream preserves this stable secret link and both startup orders.
      activation.hermesAgentEnvironment =
        let
          linkEnvironment = ''
            run mkdir -p ${lib.escapeShellArg configDir}
            run ln -sfn ${
              lib.escapeShellArg config.sops.secrets."hermes-env".path
            } ${lib.escapeShellArg "${configDir}/.env"}
          '';
        in
        if isDarwin then
          lib.hm.dag.entryBetween [ "setupLaunchAgents" ] [ "hermesAgentSetup" "sops-nix" ] linkEnvironment
        else
          lib.hm.dag.entryBetween [ "reloadSystemd" ] [ "hermesAgentSetup" ] linkEnvironment;
    };

    warnings = lib.optional (
      cfg.enableDesktop && cfg.desktopPackage == null
    ) "hermesAgent: desktopPackage not available for system ${system}";
  };
}
