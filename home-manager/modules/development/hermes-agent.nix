{
  config,
  inputs,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.development.hermesAgent;
  system = pkgs.stdenv.hostPlatform.system;
  isDarwin = pkgs.stdenv.hostPlatform.isDarwin;
  homeDir = config.home.homeDirectory;

  hermesInputs = inputs.hermes-agent.inputs // {
    self = inputs.hermes-agent;
  };
  hermesPackageModule = import "${inputs.hermes-agent}/nix/packages.nix" {
    inputs = hermesInputs;
  };
  hermesPackages = hermesPackageModule.perSystem {
    inherit lib pkgs;
    inputs' = {
      npm-lockfile-fix.packages.default =
        inputs.hermes-agent.inputs.npm-lockfile-fix.packages.${system}.default;
    };
  };
  baseHermesAgentPackage = hermesPackages.packages.full or null;

  hermesAgentWithExtras =
    if baseHermesAgentPackage == null then
      null
    else if cfg.extraDependencyGroups != [ ] then
      baseHermesAgentPackage.override (old: {
        extraDependencyGroups = lib.unique (
          (old.extraDependencyGroups or [ ]) ++ cfg.extraDependencyGroups
        );
      })
    else
      baseHermesAgentPackage;

  voiceRuntimeLibVar = if isDarwin then "DYLD_FALLBACK_LIBRARY_PATH" else "LD_LIBRARY_PATH";
  voiceRuntimeLibPath = lib.concatStringsSep ":" (
    lib.filter (s: s != "") [
      (lib.makeLibraryPath [ pkgs.portaudio ])
      config.modules.core.gpu.cudaLibraryPath
    ]
  );

  hermesAgentPackage =
    if hermesAgentWithExtras == null then
      null
    else
      pkgs.symlinkJoin {
        name = "hermes-agent-voice-wrapped";
        paths = [ hermesAgentWithExtras ];
        nativeBuildInputs = [ pkgs.makeWrapper ];
        postBuild = ''
          for bin in $out/bin/*; do
            if [ -L "$bin" ]; then
              target=$(readlink -f "$bin")
              rm "$bin"
              makeWrapper "$target" "$bin" --prefix ${voiceRuntimeLibVar} : "${voiceRuntimeLibPath}"
            fi
          done
        '';
        inherit (hermesAgentWithExtras) meta;
        passthru = hermesAgentWithExtras.passthru or { };
      };

  baseHermesDesktopPackage =
    if hermesAgentWithExtras == null then null else hermesAgentWithExtras.hermesDesktop or null;

  hermesDesktopPackage =
    if baseHermesDesktopPackage == null then
      null
    else
      baseHermesDesktopPackage.overrideAttrs (old: {
        # Reroute HERMES_DESKTOP_HERMES to voice-wrapped hermesAgentPackage
        installPhase =
          builtins.replaceStrings [ (lib.getExe hermesAgentWithExtras) ] [ (lib.getExe hermesAgentPackage) ]
            old.installPhase;
      });

  yamlFormat = pkgs.formats.yaml { };

  managedConfig = yamlFormat.generate "hermes-agent-config.yaml" cfg.settings;
  configDir = "${homeDir}/.hermes";

  launchdEnv = {
    HOME = homeDir;
    HERMES_HOME = configDir;
    HERMES_MANAGED = "true";
    ${voiceRuntimeLibVar} = voiceRuntimeLibPath;
    PATH =
      lib.makeBinPath [
        cfg.package
        pkgs.bash
        pkgs.coreutils
      ]
      + ":/usr/bin:/bin";
  };

  mkLaunchdService =
    {
      label,
      args,
      logPrefix,
    }:
    {
      enable = true;
      config = {
        Label = label;
        ProgramArguments = args;
        KeepAlive = true;
        StandardOutPath = "${configDir}/${logPrefix}.log";
        StandardErrorPath = "${configDir}/${logPrefix}.err.log";
        EnvironmentVariables = launchdEnv;
        WorkingDirectory = configDir;
      };
    };

  mkSystemdService =
    {
      description,
      execStart,
    }:
    {
      Unit = {
        Description = description;
      };
      Service = {
        ExecStart = execStart;
        Restart = "always";
        RestartSec = 5;
        Environment = [
          "HOME=${homeDir}"
          "HERMES_HOME=${configDir}"
          "HERMES_MANAGED=true"
          "${voiceRuntimeLibVar}=${voiceRuntimeLibPath}"
        ];
        WorkingDirectory = configDir;
      };
      Install.WantedBy = [ "default.target" ];
    };
in
{
  options.modules.development.hermesAgent = {
    enable = lib.mkEnableOption "hermes-agent configuration";

    enableGateway = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Whether to run hermes-agent gateway as a background service";
    };

    enableDashboard = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Whether to run hermes-agent web dashboard as a background service";
    };

    enableDesktop = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Whether to install the hermes-agent desktop app";
    };

    dashboardPort = lib.mkOption {
      type = lib.types.port;
      default = 9119;
      description = "Port for the hermes-agent web dashboard";
    };

    extraDependencyGroups = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ ];
      description = "Additional dependency groups added on top of Hermes Agent's `full` package";
      example = [
        "mistral"
        "nemo-relay"
      ];
    };

    package = lib.mkOption {
      type = lib.types.nullOr lib.types.package;
      default = hermesAgentPackage;
      defaultText = lib.literalExpression "hermesPackages.packages.full";
      description = "hermes-agent package";
    };

    desktopPackage = lib.mkOption {
      type = lib.types.nullOr lib.types.package;
      default = hermesDesktopPackage;
      defaultText = lib.literalExpression "hermesAgentWithExtras.hermesDesktop";
      description = "hermes-agent desktop package";
    };

    settings = lib.mkOption {
      type = yamlFormat.type;
      default = {
        terminal.cwd = homeDir;
      };
      description = "Initial config.yaml settings (seeded once, hermes-agent owns the file after)";
    };
  };

  config = lib.mkIf cfg.enable {
    home.packages =
      lib.optional (cfg.package != null) cfg.package
      ++ lib.optional (cfg.enableDesktop && cfg.desktopPackage != null) cfg.desktopPackage;

    warnings =
      lib.optional (cfg.package == null) "hermesAgent: package not available for system ${system}"
      ++ lib.optional (
        cfg.enableDesktop && cfg.desktopPackage == null
      ) "hermesAgent: desktopPackage not available for system ${system}";

    home.activation.hermesAgentBootstrap = lib.mkIf (cfg.package != null) (
      lib.hm.dag.entryAfter [ "writeBoundary" "sops-nix" ] ''
        run mkdir -p "${configDir}"
        if [[ -f "${config.sops.secrets."hermes-env".path}" ]]; then
          run ln -sf "${config.sops.secrets."hermes-env".path}" "${configDir}/.env"
        elif [[ ! -e "${configDir}/.env" && ! -L "${configDir}/.env" ]]; then
          run touch "${configDir}/.env"
          run chmod 600 "${configDir}/.env"
        fi
      ''
    );

    home.activation.hermesAgentConfig = lib.mkIf (cfg.package != null && cfg.settings != { }) (
      lib.hm.dag.entryAfter [ "hermesAgentBootstrap" ] ''
        if [[ ! -f "${configDir}/config.yaml" ]]; then
          run cp "${managedConfig}" "${configDir}/config.yaml"
          run chmod 644 "${configDir}/config.yaml"
        fi
      ''
    );

    launchd.agents.hermes-agent-gateway =
      lib.mkIf (cfg.enableGateway && isDarwin && cfg.package != null)
        (mkLaunchdService {
          label = "com.nousresearch.hermes-agent-gateway";
          args = [
            (lib.getExe' cfg.package "hermes")
            "gateway"
            "run"
          ];
          logPrefix = "gateway";
        });

    launchd.agents.hermes-agent-dashboard =
      lib.mkIf (cfg.enableDashboard && isDarwin && cfg.package != null)
        (mkLaunchdService {
          label = "com.nousresearch.hermes-agent-dashboard";
          args = [
            (lib.getExe' cfg.package "hermes")
            "dashboard"
            "--no-open"
            "--skip-build"
            "--port"
            (toString cfg.dashboardPort)
          ];
          logPrefix = "dashboard";
        });

    systemd.user.services.hermes-agent-gateway =
      lib.mkIf (cfg.enableGateway && !isDarwin && cfg.package != null)
        (mkSystemdService {
          description = "Hermes Agent Gateway";
          execStart = "${lib.getExe' cfg.package "hermes"} gateway run";
        });

    systemd.user.services.hermes-agent-dashboard =
      lib.mkIf (cfg.enableDashboard && !isDarwin && cfg.package != null)
        (mkSystemdService {
          description = "Hermes Agent Web Dashboard";
          execStart = "${lib.getExe' cfg.package "hermes"} dashboard --no-open --skip-build --port ${toString cfg.dashboardPort}";
        });

    xdg.desktopEntries = lib.mkIf (cfg.enableDesktop && !isDarwin && cfg.desktopPackage != null) {
      hermes-desktop = {
        name = "Hermes Desktop";
        exec = "${lib.getExe cfg.desktopPackage} %U";
        comment = "Hermes Agent desktop app";
        terminal = false;
        categories = [ "Development" ];
        settings.StartupWMClass = "Hermes";
      };
    };
  };
}
