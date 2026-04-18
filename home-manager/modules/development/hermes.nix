{
  config,
  lib,
  pkgs,
  inputs,
  ...
}:

let
  cfg = config.modules.development.hermes;
  system = pkgs.stdenv.hostPlatform.system;
  isDarwin = pkgs.stdenv.hostPlatform.isDarwin;
  homeDir = config.home.homeDirectory;

  hermesPackage = inputs.hermes-agent.packages.${system}.default or null;
  yamlFormat = pkgs.formats.yaml { };

  managedConfig = yamlFormat.generate "hermes-config.yaml" cfg.settings;
in
{
  options.modules.development.hermes = {
    enable = lib.mkEnableOption "hermes-agent";

    enableGateway = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Run hermes gateway as a background service";
    };

    package = lib.mkOption {
      type = lib.types.nullOr lib.types.package;
      default = hermesPackage;
      defaultText = lib.literalExpression "inputs.hermes-agent.packages.\${system}.default";
      description = "Hermes agent package";
    };

    settings = lib.mkOption {
      type = yamlFormat.type;
      default = { };
      description = "Initial config.yaml settings (seeded once, hermes owns the file after)";
    };
  };

  config = lib.mkIf cfg.enable {
    home.packages = lib.optional (cfg.package != null) cfg.package;

    warnings = lib.optional (cfg.package == null) "hermes: package not available for system ${system}";

    home.activation.hermesConfig = lib.mkIf (cfg.package != null && cfg.settings != { }) (
      let
        configDir = "${homeDir}/.hermes";
      in
      lib.hm.dag.entryAfter [ "writeBoundary" ] ''
        run mkdir -p "${configDir}"
        if [[ ! -f "${configDir}/config.yaml" ]]; then
          run cp "${managedConfig}" "${configDir}/config.yaml"
          run chmod 644 "${configDir}/config.yaml"
        fi
        if [[ ! -f "${configDir}/.env" ]]; then
          run touch "${configDir}/.env"
          run chmod 600 "${configDir}/.env"
        fi
      ''
    );

    launchd.agents.hermes-gateway = lib.mkIf (cfg.enableGateway && isDarwin && cfg.package != null) {
      enable = true;
      config = {
        Label = "com.nousresearch.hermes-gateway";
        ProgramArguments = [
          "${cfg.package}/bin/hermes"
          "gateway"
          "run"
        ];
        KeepAlive = true;
        RunAtLoad = true;
        StandardOutPath = "${homeDir}/.hermes/gateway.log";
        StandardErrorPath = "${homeDir}/.hermes/gateway.err.log";
        EnvironmentVariables = {
          HOME = homeDir;
          HERMES_HOME = "${homeDir}/.hermes";
          PATH = lib.makeBinPath [ cfg.package pkgs.coreutils ] + ":/usr/bin:/bin";
        };
        WorkingDirectory = "${homeDir}/.hermes";
      };
    };

    systemd.user.services.hermes-gateway = lib.mkIf (cfg.enableGateway && !isDarwin && cfg.package != null) {
      Unit = {
        Description = "Hermes Agent Gateway";
        After = [ "network.target" ];
      };
      Service = {
        ExecStart = "${cfg.package}/bin/hermes gateway run";
        Restart = "on-failure";
        RestartSec = 5;
        Environment = [
          "HERMES_HOME=${homeDir}/.hermes"
        ];
        WorkingDirectory = "${homeDir}/.hermes";
      };
      Install.WantedBy = [ "default.target" ];
    };
  };
}
