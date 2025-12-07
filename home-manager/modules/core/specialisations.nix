{ config, lib, ... }:
let
  cfg = config.modules.core.specialisations;

  mkSpecialisation =
    {
      name,
      email,
      signature,
    }:
    {
      configuration =
        let
          gpgKeyId = config.modules.core.constants.gpg.keyId;
          gpgFingerprint = config.modules.core.constants.gpg.fingerprint;
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
        };
    };
in
{
  options.modules.core.specialisations = {
    enable = lib.mkEnableOption "specialisations configuration";
  };

  config = lib.mkIf cfg.enable {
    specialisation = {
      work = mkSpecialisation {
        name = "work";
        email = config.modules.core.constants.workEmail;
        signature = ''
          ${config.modules.core.constants.username} - R&D Software Engineer
          SAP Labs France
        '';
      };

      personal = mkSpecialisation {
        name = "personal";
        email = config.modules.core.constants.email;
        signature = ''
          ${config.modules.core.constants.username} aka fraggle
          Piment Noir - https://piment-noir.org
        '';
      };
    };
  };
}
