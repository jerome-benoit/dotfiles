{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.development.hermesAgent;
  system = pkgs.stdenv.hostPlatform.system;
  isDarwin = pkgs.stdenv.hostPlatform.isDarwin;
  homeDir = config.home.homeDirectory;

  needsPortaudio = lib.elem "voice" cfg.extraDependencyGroups;
  voiceRuntimeLibVar = if isDarwin then "DYLD_FALLBACK_LIBRARY_PATH" else "LD_LIBRARY_PATH";
  voiceRuntimeLibPath = lib.concatStringsSep ":" (
    lib.filter (s: s != "") [
      (lib.makeLibraryPath [ pkgs.portaudio ])
      config.modules.core.gpu.cudaLibraryPath
    ]
  );

  baseHermesAgentPackage = pkgs.hermes-agent or null;

  hermesAgentPackage =
    if baseHermesAgentPackage == null then
      null
    else
      let
        withGroups =
          if cfg.extraDependencyGroups != [ ] then
            baseHermesAgentPackage.override { inherit (cfg) extraDependencyGroups; }
          else
            baseHermesAgentPackage;
      in
      if !needsPortaudio then
        withGroups
      else
        pkgs.symlinkJoin {
          name = "hermes-agent-voice-wrapped";
          paths = [ withGroups ];
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
          inherit (withGroups) meta;
          passthru = withGroups.passthru or { };
        };
  yamlFormat = pkgs.formats.yaml { };

  managedConfig = yamlFormat.generate "hermes-agent-config.yaml" cfg.settings;
  configDir = "${homeDir}/.hermes";

  launchdEnv = {
    HOME = homeDir;
    HERMES_HOME = configDir;
    HERMES_MANAGED = "true";
    PATH =
      lib.makeBinPath [
        cfg.package
        pkgs.bash
        pkgs.coreutils
      ]
      + ":/usr/bin:/bin";
  }
  // lib.optionalAttrs needsPortaudio { ${voiceRuntimeLibVar} = voiceRuntimeLibPath; };

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
        ]
        ++ lib.optional needsPortaudio "${voiceRuntimeLibVar}=${voiceRuntimeLibPath}";
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

    dashboardPort = lib.mkOption {
      type = lib.types.port;
      default = 9119;
      description = "Port for the hermes-agent web dashboard";
    };

    extraDependencyGroups = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [
        "anthropic"
        "azure-identity"
        "bedrock"
        "daytona"
        "dingtalk"
        "edge-tts"
        "exa"
        "fal"
        "feishu"
        "firecrawl"
        "hindsight"
        "honcho"
        "matrix"
        "messaging"
        "modal"
        "parallel-web"
        "slack"
        "tts-premium"
        "voice"
      ];
      description = "Additional pyproject.toml dependency groups to bundle in the sealed venv";
      example = [
        "anthropic"
        "messaging"
        "voice"
      ];
    };

    package = lib.mkOption {
      type = lib.types.nullOr lib.types.package;
      default = hermesAgentPackage;
      defaultText = lib.literalExpression "pkgs.hermes-agent";
      description = "hermes-agent package";
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
    home.packages = lib.optional (cfg.package != null) cfg.package;

    warnings = lib.optional (
      cfg.package == null
    ) "hermesAgent: package not available for system ${system}";

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
  };
}
