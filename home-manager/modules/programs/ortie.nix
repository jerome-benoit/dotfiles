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
  brokerBackends = [
    "gmail"
    "msgraph"
  ];
  brokerUsers =
    backend:
    lib.optionals config.programs.himalaya.enable (
      builtins.filter (
        name:
        let
          account = config.accounts.email.accounts.${name};
        in
        account.himalaya.enable
        &&
          (account.himalaya.settings.${backend}.auth.token.command or null) == [
            "ortie"
            "token"
            "show"
            "-a"
            backend
          ]
      ) email.activeAccounts
    );
  neededBrokers = builtins.filter (backend: brokerUsers backend != [ ]) brokerBackends;
  brokerAccount = backend: config.accounts.email.accounts.${builtins.head (brokerUsers backend)};
  providerDefaults = {
    gmail = {
      client-id = email.oauth.gmail.clientId;
      client-secret.command = [
        "cat"
        config.sops.secrets."ortie-gmail-client-secret".path
      ];
      endpoints = {
        authorization = "https://accounts.google.com/o/oauth2/v2/auth";
        token = "https://oauth2.googleapis.com/token";
        redirection = "http://localhost:8401";
      };
      scopes = [ "https://mail.google.com/" ];
      extras = {
        access_type = "offline";
        prompt = "consent";
        login_hint = (brokerAccount "gmail").address;
      };
    };
    msgraph = {
      client-id = "14d82eec-204b-4c2f-b7e8-296a70dab67e";
      endpoints = {
        authorization = "https://login.microsoftonline.com/${constants.work.tenantId}/oauth2/v2.0/authorize";
        token = "https://login.microsoftonline.com/${constants.work.tenantId}/oauth2/v2.0/token";
        redirection = "http://localhost:8400";
      };
      scopes = [
        "https://graph.microsoft.com/User.Read"
        "https://graph.microsoft.com/Mail.ReadWrite"
        "https://graph.microsoft.com/Mail.Send"
        "offline_access"
      ];
    };
  };
  mkBroker =
    backend:
    let
      account = cfg.settings.accounts.${backend};
      namespace = if backend == "gmail" then (brokerAccount backend).address else constants.work.tenantId;
      storageAccount = "${backend}/${namespace}/${account.client-id}";
    in
    lib.mapAttrsRecursive (_: value: lib.mkDefault value) (
      providerDefaults.${backend}
      // {
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
in
{
  options.modules.programs.ortie = {
    enable = lib.mkEnableOption "Ortie configuration";
    settings = lib.mkOption {
      type = lib.types.submodule { freeformType = tomlFormat.type; };
      default = { };
      description = "Ortie configuration. gmail/msgraph are managed aliases rendered only for active Himalaya brokers; use other names for standalone accounts.";
    };
  };

  config = lib.mkIf cfg.enable {
    home.packages = [ pkgs.ortie ];
    xdg.configFile =
      let
        accounts = lib.filterAttrs (
          name: _: !(builtins.elem name brokerBackends) || builtins.elem name neededBrokers
        ) (cfg.settings.accounts or { });
      in
      lib.mkIf (accounts != { }) {
        "ortie/config.toml".source = tomlFormat.generate "ortie.config.toml" (
          cfg.settings // { inherit accounts; }
        );
      };

    # Brokers follow the effective native API token commands.
    modules.programs.ortie.settings.accounts = lib.genAttrs neededBrokers mkBroker;

    # App credentials must not depend on renderer settings that reference SOPS paths.
    sops.secrets."ortie-gmail-client-secret" =
      lib.mkIf (email.enable && builtins.hasAttr "gmail" email.oauth)
        {
          key = "email/oauth/gmail/clientSecret";
          mode = "0600";
        };

    services.gnome-keyring = lib.mkIf (pkgs.stdenv.hostPlatform.isLinux && neededBrokers != [ ]) {
      enable = lib.mkDefault (!config.services.pass-secret-service.enable);
      components = [ "secrets" ];
    };
  };
}
