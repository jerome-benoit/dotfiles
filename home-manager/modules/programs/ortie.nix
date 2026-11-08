{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.programs.ortie;
  email = config.modules.core.email;
  constants = config.modules.core.constants;
  tomlFormat = pkgs.formats.toml { };
  python = pkgs.python3.withPackages (ps: [ ps.keyring ]);
  tokenStorage = pkgs.writeScript "ortie-token-storage" (
    "#!${python}/bin/python3\n" + builtins.readFile ./ortie-token-storage.py
  );
  needsGraphBroker =
    config.programs.himalaya.enable
    && builtins.any (
      name:
      let
        account = config.accounts.email.accounts.${name};
      in
      account.himalaya.enable
      &&
        (account.himalaya.settings.msgraph.auth.token.command or null) == [
          "ortie"
          "token"
          "show"
          "-a"
          "msgraph"
        ]
    ) email.activeAccounts;
  tenantId = constants.work.tenantId;
  graphAccount = cfg.settings.accounts.msgraph;
  storageAccount = "msgraph/${tenantId}/${graphAccount.client-id}";
in
{
  options.modules.programs.ortie = {
    enable = lib.mkEnableOption "ortie configuration";
    settings = lib.mkOption {
      type = lib.types.submodule { freeformType = tomlFormat.type; };
      default = { };
      description = "Ortie configuration; tokens belong in the system keyring, not in settings.";
    };
  };

  config = lib.mkIf cfg.enable {
    home.packages = [ pkgs.ortie ];
    xdg.configFile = lib.mkIf ((cfg.settings.accounts or { }) != { }) {
      "ortie/config.toml".source = tomlFormat.generate "ortie.config.toml" cfg.settings;
    };

    # Default broker for active Graph accounts using the msgraph alias.
    modules.programs.ortie.settings.accounts.msgraph = lib.mkIf needsGraphBroker (
      lib.mapAttrsRecursive (_: value: lib.mkDefault value) {
        client-id = "14d82eec-204b-4c2f-b7e8-296a70dab67e";
        endpoints = {
          authorization = "https://login.microsoftonline.com/${tenantId}/oauth2/v2.0/authorize";
          token = "https://login.microsoftonline.com/${tenantId}/oauth2/v2.0/token";
          redirection = "http://localhost:8400";
        };
        scopes = [
          "https://graph.microsoft.com/User.Read"
          "https://graph.microsoft.com/Mail.ReadWrite"
          "https://graph.microsoft.com/Mail.Send"
          "offline_access"
        ];
        auto-refresh = true;
        storage = {
          read.command = [
            "${tokenStorage}"
            "read"
            storageAccount
          ];
          write.command = [
            "${tokenStorage}"
            "write"
            storageAccount
          ];
        };
      }
    );

    services.gnome-keyring = lib.mkIf (pkgs.stdenv.hostPlatform.isLinux && needsGraphBroker) {
      enable = lib.mkDefault (!config.services.pass-secret-service.enable);
      components = [ "secrets" ];
    };
  };
}
