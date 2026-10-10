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

    accounts.email.accounts = lib.genAttrs email.selectedAccounts (_: {
      himalaya.enable = true;
    });

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
