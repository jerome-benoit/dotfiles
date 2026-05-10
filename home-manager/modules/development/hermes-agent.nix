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

  hermesAgentPackage = pkgs.hermes-agent or null;
  yamlFormat = pkgs.formats.yaml { };

  managedConfig = yamlFormat.generate "hermes-agent-config.yaml" cfg.settings;
  configDir = "${homeDir}/.hermes";

  launchdEnv = {
    HOME = homeDir;
    HERMES_HOME = configDir;
    HERMES_MANAGED = "true";
    PATH = lib.makeBinPath [
      cfg.package
      pkgs.git
      pkgs.bash
      pkgs.coreutils
    ] + ":/usr/bin:/bin";
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
          "PATH=${lib.makeBinPath [
            cfg.package
            pkgs.git
            pkgs.bash
            pkgs.coreutils
          ]}"
        ];
        WorkingDirectory = configDir;
      };
      Install.WantedBy = [ "default.target" ];
    };
in
{
  options.modules.development.hermesAgent = {
    enable = lib.mkEnableOption "hermes-agent";

    enableGateway = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Run hermes-agent gateway as a background service";
    };

    enableDashboard = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Run hermes-agent web dashboard as a background service";
    };

    dashboardPort = lib.mkOption {
      type = lib.types.port;
      default = 9119;
      description = "Port for the hermes-agent web dashboard";
    };

    package = lib.mkOption {
      type = lib.types.nullOr lib.types.package;
      default = hermesAgentPackage;
      defaultText = lib.literalExpression "pkgs.hermes-agent";
      description = "hermes-agent package";
    };

    settings = lib.mkOption {
      type = yamlFormat.type;
      default = { };
      description = "Initial config.yaml settings (seeded once, hermes-agent owns the file after)";
    };
  };

  config = lib.mkIf cfg.enable {
    home.packages = lib.optional (cfg.package != null) cfg.package;

    warnings = lib.optional (
      cfg.package == null
    ) "hermesAgent: package not available for system ${system}";

    home.activation.hermesAgentBootstrap = lib.mkIf (cfg.package != null) (
      lib.hm.dag.entryAfter [ "writeBoundary" ] ''
        run mkdir -p "${configDir}"
        if [[ ! -f "${configDir}/.env" ]]; then
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
            "${cfg.package}/bin/hermes"
            "gateway"
          ];
          logPrefix = "gateway";
        });

    launchd.agents.hermes-agent-dashboard =
      lib.mkIf (cfg.enableDashboard && isDarwin && cfg.package != null)
        (mkLaunchdService {
          label = "com.nousresearch.hermes-agent-dashboard";
          args = [
            "${cfg.package}/bin/hermes"
            "dashboard"
            "--no-open"
            "--port"
            (toString cfg.dashboardPort)
          ];
          logPrefix = "dashboard";
        });

    systemd.user.services.hermes-agent-gateway =
      lib.mkIf (cfg.enableGateway && !isDarwin && cfg.package != null)
        (mkSystemdService {
          description = "Hermes Agent Gateway";
          execStart = "${cfg.package}/bin/hermes gateway";
        });

    systemd.user.services.hermes-agent-dashboard =
      lib.mkIf (cfg.enableDashboard && !isDarwin && cfg.package != null)
        (mkSystemdService {
          description = "Hermes Agent Web Dashboard";
          execStart = "${cfg.package}/bin/hermes dashboard --no-open --port ${toString cfg.dashboardPort}";
        });
  };
}
