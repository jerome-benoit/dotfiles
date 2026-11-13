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
  miseEnabled = config.programs.mise.enable && config.programs.mise.package != null;
  # Resolve only stable shims; each command still selects its tool from its cwd.
  misePath = pkgs.writeShellScript "hermes-mise-path" ''
    set -euo pipefail
    miseActivation=$(${lib.getExe config.programs.mise.package} activate bash --shims)
    eval "$miseActivation"
    printf '%s' "$PATH"
  '';
  # Workaround: pnpm's macOS clone probe leaves an empty directory in the store.
  # Remove when upstream excludes virtual-store artifacts from the archive.
  hermesCallPackage =
    if isDarwin then
      pkgs.newScope {
        fetchPnpmDeps =
          args:
          (pkgs.fetchPnpmDeps args).overrideAttrs (previousAttrs: {
            preFixup = (previousAttrs.preFixup or "") + ''
              if [ -d "$storePath/v11/links" ]; then
                rmdir "$storePath/v11/links"
              fi
            '';
          });
      }
    else
      pkgs.callPackage;
  # Workaround: local login profiles can put their tools ahead of inherited shims.
  # Patch the workspace wheel, not the outer wrapper or its filtered lock source.
  # Remove when Hermes provides an additive post-login PATH hook.
  miseOverlay = _final: previous: {
    hermes-agent = previous.hermes-agent.overrideAttrs (old: {
      patches = (old.patches or [ ]) ++ [
        ../../../patches/hermes-agent-terminal-mise-shims.patch
      ];
      postPatch = (old.postPatch or "") + ''
        substituteInPlace tools/environments/local.py \
          --replace-fail '@HERMES_NIX_MISE_PATH@' '${misePath}'
      '';
    });
  };
  baseHermesAgentPackage = inputs.hermes-agent.packages.${system}.default.override (
    {
      callPackage =
        path: args:
        hermesCallPackage path (
          # Workaround: terminal hooks invalidate the icon interpreter and frontend builds.
          # Remove when upstream separates icon dependencies from the runtime environment.
          if miseEnabled && toString path == "${inputs.hermes-agent}/nix/icons.nix" then
            args // { venv = inputs.hermes-agent.packages.${system}.minimal.hermesVenv; }
          else if miseEnabled && toString path == "${inputs.hermes-agent}/nix/python.nix" then
            args
            // {
              uv2nix = args.uv2nix // {
                lib = args.uv2nix.lib // {
                  workspace = args.uv2nix.lib.workspace // {
                    loadWorkspace =
                      workspaceArgs:
                      let
                        workspace = args.uv2nix.lib.workspace.loadWorkspace workspaceArgs;
                      in
                      workspace
                      // {
                        mkPyprojectOverlay =
                          options: lib.composeExtensions (workspace.mkPyprojectOverlay options) miseOverlay;
                      };
                  };
                };
              };
            }
          else
            args
        );
    }
    // lib.optionalAttrs isLinux {
      # Workaround: PM applies a 0.19.2 patch to nixpkgs' patchelf 0.15.2.
      # Remove when upstream selects a compatible patchelf with the header-overlap fix.
      pmPackages = lib.mapAttrs (
        _: package:
        package.overrideAttrs (previousAttrs: {
          nativeBuildInputs = map (
            input: if (input.pname or null) == "patchelf" then pkgs.buildPackages.patchelfUnstable else input
          ) previousAttrs.nativeBuildInputs;
        })
      ) (pkgs.callPackage "${inputs.hermes-agent}/nix/pm-packages.nix" { });
    }
  );

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

  # Workaround: upstream omits audio library search paths and Linux discovery tools.
  # Remove when its wrappers expose these libraries and binutils.
  hermesAgentPackage = baseHermesAgentPackage.overrideAttrs (previousAttrs: {
    postFixup = (previousAttrs.postFixup or "") + ''
      for bin in "$out"/bin/*; do
        [ -x "$bin" ] || continue
        wrapProgram "$bin" --prefix ${voiceRuntimeLibVar} : "${voiceRuntimeLibPath}" \
          ${lib.optionalString isLinux "--prefix PATH : ${lib.makeBinPath [ pkgs.binutils ]}"}
      done
    '';
    # Expose the service launcher without building the application/model closure.
    passthru = (previousAttrs.passthru or { }) // {
      integrationSecretGate = secretGate;
      integrationGatewayLogin = gatewayLogin;
    };
  });
  effectiveHermesAgentPackage = hermesModuleCommon.effectivePackage serviceCfg;
  hermesDesktopPackage = effectiveHermesAgentPackage.hermesDesktop or null;

  # Workaround: mkStateScript quotes mkdir but not the other state destinations.
  # Render safe shell-word placeholders, then quote the real roots exactly once.
  # Keep the actual working directory in config.yaml, not its shell placeholder.
  # Remove when upstream quotes every use of both destination roots.
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

  # Workaround: launchd starts Hermes and sops independently at login.
  # Remove when upstream gates service startup on its secret provider.
  secretGate = pkgs.writeShellScript "hermes-secret-ready" ''
    attempts=0
    until [ -r ${lib.escapeShellArg config.sops.secrets."hermes-env".path} ]; do
      if [ "$attempts" -ge 60 ]; then
        echo "Hermes secret unavailable after 60 seconds" >&2
        exit 1
      fi
      attempts=$((attempts + 1))
      ${pkgs.coreutils}/bin/sleep 1
    done
    exec "$@"
  '';
  # Login profiles run first; the gateway and local snapshots share one resolver.
  gatewayEnvironment = pkgs.writeShellScript "hermes-gateway-environment" ''
    set -euo pipefail
    export PATH="''${PATH:+$PATH:}$1"
    shift
    ${lib.optionalString miseEnabled ''
      PATH=$(${misePath})
      export PATH HERMES_NIX_MISE_SHIMS=1
    ''}
    exec "$@"
  '';
  # Workaround: upstream service launchers omit the account's login environment.
  # Remove when upstream supports the account's non-interactive login environment.
  gatewayLogin = pkgs.writeShellScript "hermes-gateway-login" ''
    set -euo pipefail
    loginShell=$(
      ${pkgs.getent}/bin/getent passwd "$(${pkgs.coreutils}/bin/id -u)" \
        | ${pkgs.coreutils}/bin/cut -d: -f7
    )
    if [[ "$loginShell" != /* || ! -x "$loginShell" ]]; then
      echo "Hermes gateway requires an executable absolute login shell" >&2
      exit 1
    fi
    case "''${loginShell##*/}" in
      bash|zsh|sh|dash|ksh|mksh) ;;
      *) echo "Hermes gateway requires a POSIX-compatible login shell: $loginShell" >&2; exit 1 ;;
    esac
    systemPath=$(${pkgs.getconf}/bin/getconf PATH)
    export PATH="''${PATH:+$PATH:}$systemPath"
    export SHELL="$loginShell"
    exec "$loginShell" -lc 'exec "$@"' hermes-gateway \
      ${gatewayEnvironment} \
      ${lib.escapeShellArg "${config.home.profileDirectory}/bin"}"''${PATH:+:$PATH}" "$@"
  '';
in
{
  options.modules.development.hermesAgent = {
    enable = lib.mkEnableOption "Hermes Agent configuration";

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
      defaultText = lib.literalExpression "effectiveHermesAgentPackage.hermesDesktop or null";
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
          hermes-agent = {
            Unit = {
              After = [ "sops-nix.service" ];
              Requires = [ "sops-nix.service" ];
            };
            Service.ExecStart = lib.mkForce (
              lib.escapeShellArgs ([ gatewayLogin ] ++ hermesModuleCommon.gatewayArgv serviceCfg)
            );
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

    launchd.agents = lib.mkIf isDarwin (
      lib.mkMerge [
        (lib.mkIf cfg.enableGateway {
          hermes-agent.config.ProgramArguments = lib.mkForce (
            [
              "${secretGate}"
              "${gatewayLogin}"
            ]
            ++ hermesModuleCommon.gatewayArgv serviceCfg
          );
        })
        (lib.mkIf cfg.enableDashboard {
          hermes-backend.config.ProgramArguments = lib.mkForce (
            [ "${secretGate}" ]
            ++ hermesModuleCommon.backendArgv {
              inherit pkgs;
              cfg = serviceCfg;
            }
          );
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

      # Workaround: Linux needs the stable secret link before reloadSystemd.
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
