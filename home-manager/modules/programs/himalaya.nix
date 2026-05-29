{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.programs.himalaya;
  constants = config.modules.core.constants;

  commonSettings = {
    signature = "${config.home.homeDirectory}/.signature";
    envelope.list.datetime-local-tz = true;
    envelope.list.page-size = 50;
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
        folders = {
          inbox = "INBOX";
          sent = "Sent";
          drafts = "Drafts";
          trash = "Trash";
        };
        passwordCommand = [
          "cat"
          config.sops.secrets."himalaya-imap-password".path
        ];
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
        himalaya = {
          enable = true;
          settings = commonSettings;
        };
      };

    };
  };
}
