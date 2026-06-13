{
  config,
  lib,
  ...
}:

let
  cfg = config.modules.core.specialisations;
  constants = config.modules.core.constants;
  sshEnabled = config.modules.programs.ssh.enable;
  isZeus = constants.hostname == constants.hosts.zeus;

  mkSpecialisation =
    {
      name,
      email,
      signature,
      theme,
      sshSettings ? { },
      sopsOverrides ? { },
    }:
    {
      configuration =
        let
          gpgKeyId = constants.identity.gpg.keyId;
          gpgFingerprint = constants.identity.gpg.fingerprint;
        in
        lib.mkMerge [
          {
            home.file.".signature".text = lib.mkForce ''
              ${signature}
              OpenPGP Key ID : ${gpgKeyId}
              Key fingerprint : ${gpgFingerprint}
            '';

            programs.git.settings.user = {
              email = lib.mkForce email;
              signingKey = lib.mkForce gpgKeyId;
            };

            programs.zsh.shellAliases = {
              hm = lib.mkForce "_hm_switch --specialisation ${name}";
              hmw = "_hm_switch --specialisation work";
              hmp = "_hm_switch --specialisation personal";
            };

            programs.ssh.settings = lib.mkIf sshEnabled sshSettings;

            modules.themes.active = lib.mkForce theme;
          }
          sopsOverrides
        ];
    };
in
{
  options.modules.core.specialisations = {
    enable = lib.mkEnableOption "specialisations configuration";
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = config.modules.development.git.enable;
        message = "specialisations: git module must be enabled (set modules.development.git.enable = true)";
      }
      {
        assertion = config.modules.shell.zsh.enable;
        message = "specialisations: zsh module must be enabled (set modules.shell.zsh.enable = true)";
      }
    ];

    specialisation = {
      work = mkSpecialisation {
        name = "work";
        email = constants.work.email;
        signature = ''
          ${constants.identity.fullName} - ${constants.work.jobTitle}
          ${constants.work.employer}
        '';
        theme = "tokyoNightStorm";
        sshSettings = {
          "*.local" = {
            User = constants.identity.username;
          };
        };
        sopsOverrides = {
          sops.secrets."hermes-env".key = lib.mkForce "hermes/work/envContent";
        };
      };

      personal = mkSpecialisation {
        name = "personal";
        email = constants.personal.email;
        signature = ''
          ${constants.identity.fullName} aka ${constants.identity.username}
          Piment Noir - https://${constants.personal.domain}
        '';
        theme = "tokyoNightStorm";
        sopsOverrides = lib.mkIf isZeus {
          sops.secrets."hermes-env".key = lib.mkForce "hermes/personal/dashboardEnvContent";
          modules.development.hermesAgent.dashboardHost = "0.0.0.0";
        };
      };
    };
  };
}
