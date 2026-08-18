{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.programs.himalaya;
  email = config.modules.core.email;
  tomlFormat = pkgs.formats.toml { };

  mkTransport =
    account: protocol: transport:
    let
      starttls = transport.tls.enable && transport.tls.useStartTls;
      scheme = if transport.tls.enable && !starttls then "${protocol}s" else protocol;
      authority =
        if isNull transport.port then transport.host else "${transport.host}:${toString transport.port}";
    in
    {
      inherit starttls;
      server = "${scheme}://${authority}";
      sasl.login = {
        username = account.userName;
        password.command = account.passwordCommand;
      };
    };

  mkAccount =
    name:
    let
      account = config.accounts.email.accounts.${name};
    in
    {
      default = account.primary;
      mailbox.alias = lib.filterAttrs (_: value: value != null) {
        inherit (account.folders)
          drafts
          inbox
          sent
          trash
          ;
      };
    }
    // lib.optionalAttrs (account.imap != null) {
      imap = mkTransport account "imap" account.imap;
    }
    // lib.optionalAttrs (account.smtp != null) {
      smtp = mkTransport account "smtp" account.smtp;
    };

  himalayaConfig = tomlFormat.generate "himalaya-config.toml" (
    cfg.settings
    // {
      accounts = lib.genAttrs email.activeAccounts mkAccount;
    }
  );
in
{
  options.modules.programs.himalaya = {
    enable = lib.mkEnableOption "himalaya configuration";

    settings = lib.mkOption {
      type = lib.types.submodule { freeformType = tomlFormat.type; };
      default = {
        downloads-dir = config.xdg.userDirs.download;
        envelope.list = {
          datetime-local-tz = true;
          page-size = 50;
        };
      };
      description = "Global Himalaya v2 settings.";
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = email.enable;
        message = "himalaya: shared email account configuration must be enabled";
      }
    ];

    home.packages = [ pkgs.himalaya ];

    # Workaround for nix-community/home-manager#9794: the current module emits
    # v1 keys that Himalaya v2 silently ignores. Cut over atomically by enabling
    # programs.himalaya and each active account's himalaya integration,
    # moving cfg.settings to programs.himalaya.settings, then removing this
    # writer and direct package installation.
    xdg.configFile."himalaya/config.toml".source = himalayaConfig;
  };
}
