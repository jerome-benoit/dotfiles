{
  config,
  lib,
  pkgs,
  inputs,
  self,
  ...
}:

let
  cfg = config.modules.development.hermesAgent;
  system = pkgs.stdenv.hostPlatform.system;
  isDarwin = pkgs.stdenv.hostPlatform.isDarwin;
  homeDir = config.home.homeDirectory;

  baseHermesAgentPackage = inputs.hermes-agent.packages.${system}.default or null;
  hermesAgentPackage =
    if baseHermesAgentPackage != null then
      baseHermesAgentPackage.overrideAttrs (old: {
        postInstall = (old.postInstall or "") + ''
          # https://github.com/NousResearch/hermes-agent/pull/12729
          chmod -R u+w $out/share/hermes-agent/skills/productivity/google-workspace/scripts
          ${pkgs.patch}/bin/patch -d $out/share/hermes-agent/skills -p2 < ${
            self + "/patches/hermes-agent/fix-google-workspace-hermes-constants.patch"
          }
        '';
      })
    else
      null;
  yamlFormat = pkgs.formats.yaml { };

  managedConfig = yamlFormat.generate "hermes-agent-config.yaml" cfg.settings;
  configDir = "${homeDir}/.hermes";

  launchdEnv = {
    HOME = homeDir;
    HERMES_HOME = configDir;
    PATH = "/usr/bin:/bin";
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
        KeepAlive = {
          SuccessfulExit = false;
        };
        RunAtLoad = true;
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
        After = [ "network.target" ];
      };
      Service = {
        ExecStart = execStart;
        Restart = "on-failure";
        RestartSec = 5;
        Environment = [
          "HERMES_HOME=${configDir}"
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
      defaultText = lib.literalExpression "inputs.hermes-agent.packages.\${system}.default";
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
