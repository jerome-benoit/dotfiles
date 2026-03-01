{
  config,
  lib,
  ...
}:

let
  cfg = config.modules.core.specialisations;
  constants = config.modules.core.constants;
  sshEnabled = config.modules.programs.ssh.enable;

  mkSpecialisation =
    {
      name,
      email,
      signature,
      sshMatchBlocks ? { },
    }:
    {
      configuration =
        let
          gpgKeyId = constants.gpg.keyId;
          gpgFingerprint = constants.gpg.fingerprint;
        in
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
            hm = lib.mkForce "nh home switch --specialisation ${name} --impure";
            hmw = "nh home switch --specialisation work --impure";
            hmp = "nh home switch --specialisation personal --impure";
          };

          programs.ssh.matchBlocks = lib.mkIf sshEnabled sshMatchBlocks;
        };
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
        email = constants.workEmail;
        signature = ''
          ${constants.username} - R&D Software Engineer
          SAP Labs France
        '';
        sshMatchBlocks = {
          "*.local" = {
            user = "fraggle";
          };
        };
      };

      personal = mkSpecialisation {
        name = "personal";
        email = constants.primaryEmail;
        signature = ''
          ${constants.username} aka fraggle
          Piment Noir - https://piment-noir.org
        '';
      };
    };
  };
}
