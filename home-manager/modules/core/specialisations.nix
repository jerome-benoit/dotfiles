{ config, lib, ... }:
let
  cfg = config.modules.core.specialisations;
in
{
  options.modules.core.specialisations = {
    enable = lib.mkEnableOption "specialisations configuration";
  };

  config = lib.mkIf cfg.enable {
    specialisation = {
      work = {
        configuration =
          let
            gpgKeyId = config.modules.core.constants.gpg.keyId;
            gpgFingerprint = config.modules.core.constants.gpg.fingerprint;
          in
          {
            home.file.".signature".text = lib.mkForce ''
              ${config.modules.core.constants.username} - R&D Software Engineer
              SAP Labs France
              OpenPGP Key ID : ${gpgKeyId}
              Key fingerprint : ${gpgFingerprint}
            '';

            programs.git.settings.user = {
              email = lib.mkForce config.modules.core.constants.workEmail;
              signingKey = lib.mkForce gpgKeyId;
            };

            programs.zsh.shellAliases = {
              hm = lib.mkForce "nh home switch --specialisation work";
              hmw = "nh home switch --specialisation work";
              hmp = "nh home switch --specialisation personal";
            };
          };
      };

      personal = {
        configuration =
          let
            gpgKeyId = config.modules.core.constants.gpg.keyId;
            gpgFingerprint = config.modules.core.constants.gpg.fingerprint;
          in
          {
            home.file.".signature".text = lib.mkForce ''
              ${config.modules.core.constants.username} aka fraggle
              Piment Noir - https://piment-noir.org
              OpenPGP Key ID : ${gpgKeyId}
              Key fingerprint : ${gpgFingerprint}
            '';

            programs.git.settings.user = {
              email = lib.mkForce config.modules.core.constants.email;
              signingKey = lib.mkForce gpgKeyId;
            };

            programs.zsh.shellAliases = {
              hm = lib.mkForce "nh home switch --specialisation personal";
              hmw = "nh home switch --specialisation work";
              hmp = "nh home switch --specialisation personal";
            };
          };
      };
    };
  };
}
