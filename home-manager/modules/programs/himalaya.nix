{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.programs.himalaya;
  constants = config.modules.core.constants;
  isDarwin = pkgs.stdenv.hostPlatform.isDarwin;

  mkPasswordCommand =
    email:
    if isDarwin then
      [
        "/usr/bin/security"
        "find-generic-password"
        "-s"
        "himalaya"
        "-a"
        email
        "-w"
      ]
    else
      [
        (lib.getExe pkgs.pass)
        "email/${email}"
      ];

  commonSettings = {
    signature = "${config.home.homeDirectory}/.signature";
    signature-delim = "-- \n";
    envelope.list.datetime-local-tz = true;
    message.read.format = "auto";
    message.send.save-copy = true;
    message.delete.style = "folder";
  };
in
{
  options.modules.programs.himalaya = {
    enable = lib.mkEnableOption "himalaya configuration";
  };

  config = lib.mkIf cfg.enable {
    programs.himalaya = {
      enable = true;
      package = pkgs.himalaya;
      settings = {
        downloads-dir = config.xdg.userDirs.download;
      };
    };

    accounts.email.accounts = {
      piment-noir = {
        primary = true;
        address = constants.personal.email;
        userName = constants.personal.email;
        realName = constants.identity.fullName;
        passwordCommand = mkPasswordCommand constants.personal.email;
        imap = {
          host = constants.personal.mail.imapHost;
          port = 993;
          tls.enable = true;
        };
        smtp = {
          host = constants.personal.mail.smtpHost;
          port = 465;
          tls.enable = true;
        };
        gpg = {
          key = constants.identity.gpg.fingerprint;
          signByDefault = true;
        };
        himalaya = {
          enable = true;
          settings = commonSettings;
        };
      };

    };
  };
}
