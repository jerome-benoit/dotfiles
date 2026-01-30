{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.programs.himalaya;
  constants = config.modules.core.constants;
  isDarwin = pkgs.stdenv.isDarwin;

  mkPasswordCommand =
    email:
    if isDarwin then
      [
        "security"
        "find-generic-password"
        "-s"
        "himalaya"
        "-a"
        email
        "-w"
      ]
    else
      [
        "secret-tool"
        "lookup"
        "service"
        "himalaya"
        "account"
        email
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
        address = constants.primaryEmail;
        userName = constants.primaryEmail;
        realName = constants.username;
        passwordCommand = mkPasswordCommand constants.primaryEmail;
        imap = {
          host = "ssl0.ovh.net";
          port = 993;
          tls.enable = true;
        };
        smtp = {
          host = "ssl0.ovh.net";
          port = 465;
          tls.enable = true;
        };
        gpg = {
          key = constants.gpg.fingerprint;
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
