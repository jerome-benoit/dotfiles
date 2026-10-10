{
  config,
  lib,
  ...
}:

let
  cfg = config.modules.programs.himalaya;
  email = config.modules.core.email;
in
{
  options.modules.programs.himalaya = {
    enable = lib.mkEnableOption "himalaya configuration";
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = email.enable;
        message = "himalaya: shared email account configuration must be enabled";
      }
    ];

    accounts.email.accounts = lib.genAttrs email.selectedAccounts (
      name:
      let
        account = config.accounts.email.accounts.${name};
        enabled = account.enable && account.himalaya.enable;
      in
      {
        himalaya = {
          enable = true;
          # Workaround: Home Manager joins credential argv without shell quoting.
          # Remove when its Himalaya renderer preserves command arguments.
          settings = lib.mkIf (enabled && account.passwordCommand != null) (
            lib.genAttrs
              (builtins.filter (protocol: account.${protocol} != null) [
                "imap"
                "smtp"
              ])
              (_: {
                sasl.login.password.command = lib.mkOptionDefault account.passwordCommand;
              })
          );
        };
        # Override only the implicit Maildir (1500), below user defaults (1000).
        maildir = lib.mkIf (
          enabled && account.imap == null && account.jmap == null && account.smtp != null
        ) (lib.mkOverride 1490 null);
      }
    );

    programs.himalaya = {
      enable = true;
      settings = {
        downloads-dir = lib.mkDefault config.xdg.userDirs.download;
        envelope.list = {
          datetime-local-tz = lib.mkDefault true;
          page-size = lib.mkDefault 50;
        };
      };
    };
  };
}
