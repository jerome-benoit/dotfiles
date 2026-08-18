{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.programs.himalaya;
  constants = config.modules.core.constants;
  accountName = "piment-noir";
  account = config.accounts.email.accounts.${accountName};

  mkTransport =
    protocol: transport:
    let
      starttls = transport.tls.enable && transport.tls.useStartTls;
      scheme = if transport.tls.enable && !starttls then "${protocol}s" else protocol;
      authority =
        if isNull transport.port then transport.host else "${transport.host}:${toString transport.port}";
    in
    {
      inherit starttls;
      server = "${scheme}://${authority}";
      sasl.${transport.authentication} = {
        username = account.userName;
        password.command = account.passwordCommand;
      };
    };

  himalayaConfig = (pkgs.formats.toml { }).generate "himalaya-config.toml" {
    downloads-dir = config.xdg.userDirs.download;

    accounts.${accountName} = {
      default = account.primary;

      mailbox.alias = {
        inherit (account.folders)
          drafts
          inbox
          sent
          trash
          ;
      };

      envelope.list = {
        datetime-local-tz = true;
        page-size = 50;
      };

      imap = mkTransport "imap" account.imap;
      smtp = mkTransport "smtp" account.smtp;
    };
  };
in
{
  options.modules.programs.himalaya = {
    enable = lib.mkEnableOption "himalaya configuration";
  };

  config = lib.mkIf cfg.enable {
    home.packages = [ pkgs.himalaya ];

    # Workaround for nix-community/home-manager#9794: the current module emits
    # Himalaya v1 keys that v2 silently ignores. Remove this native config once
    # Home Manager generates v2 accounts.
    xdg.configFile."himalaya/config.toml".source = himalayaConfig;

    accounts.email.accounts.${accountName} = {
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
        authentication = "login";
        tls.enable = true;
      };
      smtp = {
        host = constants.personal.mail.smtpHost;
        port = 465;
        authentication = "login";
        tls.enable = true;
      };
    };
  };
}
