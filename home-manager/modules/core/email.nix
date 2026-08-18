{
  config,
  lib,
  privateConfig,
  ...
}:

let
  cfg = config.modules.core.email;
  constants = config.modules.core.constants;
  emailRegex = "^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}$";

  tlsType = lib.types.submodule {
    options = {
      enable = lib.mkOption {
        type = lib.types.bool;
        default = true;
        description = "Whether to secure the transport with TLS.";
      };
      useStartTls = lib.mkOption {
        type = lib.types.bool;
        default = false;
        description = "Whether to upgrade the connection with STARTTLS.";
      };
    };
  };

  transportType = lib.types.submodule {
    options = {
      host = lib.mkOption {
        type = lib.types.str;
        description = "Mail server hostname.";
      };
      port = lib.mkOption {
        type = lib.types.nullOr lib.types.port;
        default = null;
        description = "Mail server port, or the protocol default when null.";
      };
      authentication = lib.mkOption {
        type = lib.types.enum [ "login" ];
        description = "Authentication mechanism shared by mail clients.";
      };
      tls = lib.mkOption {
        type = tlsType;
        default = { };
        description = "Transport security settings.";
      };
    };
  };

  accountType = lib.types.submodule {
    options = {
      identity = lib.mkOption {
        type = lib.types.enum [
          "personal"
          "work"
        ];
        description = "Identity supplying the account address and display name.";
      };
      aliases = lib.mkOption {
        type = lib.types.listOf (lib.types.strMatching emailRegex);
        default = [ ];
        description = "Alternative email addresses for the account.";
      };
      userName = lib.mkOption {
        type = lib.types.nullOr lib.types.str;
        default = null;
        description = "Server login, defaulting to the identity address.";
      };
      folders = lib.mkOption {
        type = lib.types.submodule {
          options = {
            inbox = lib.mkOption { type = lib.types.str; };
            sent = lib.mkOption {
              type = lib.types.nullOr lib.types.str;
              default = "Sent";
            };
            drafts = lib.mkOption {
              type = lib.types.nullOr lib.types.str;
              default = "Drafts";
            };
            trash = lib.mkOption { type = lib.types.str; };
          };
        };
        description = "Canonical mailbox aliases.";
      };
      imap = lib.mkOption {
        type = lib.types.nullOr transportType;
        default = null;
        description = "IMAP transport settings.";
      };
      smtp = lib.mkOption {
        type = lib.types.nullOr transportType;
        default = null;
        description = "SMTP transport settings.";
      };
      credential.type = lib.mkOption {
        type = lib.types.enum [ "password" ];
        description = "Credential type materialized through sops-nix.";
      };
    };
  };

  identities = {
    personal = {
      address = constants.personal.email;
      realName = constants.identity.fullName;
    };
    work = {
      address = constants.work.email;
      realName = constants.identity.fullName;
    };
  };

  definitionNames = builtins.attrNames cfg.definitions;
  undefinedSelectedAccounts = lib.subtractLists definitionNames cfg.selectedAccounts;
  invalidNames = builtins.filter (
    name: builtins.match "^[a-z0-9][a-z0-9_-]*$" name == null
  ) definitionNames;
  selectedDefinitions = lib.getAttrs (builtins.filter (
    name: builtins.hasAttr name cfg.definitions
  ) cfg.selectedAccounts) cfg.definitions;
  activeDefinitions = lib.getAttrs cfg.activeAccounts selectedDefinitions;
  canonicalActiveAccounts = lib.getAttrs cfg.activeAccounts config.accounts.email.accounts;
  insecureTransports = lib.concatMap (
    name:
    let
      account = canonicalActiveAccounts.${name};
    in
    lib.optional (account.imap != null && !account.imap.tls.enable) "${name}.imap"
    ++ lib.optional (account.smtp != null && !account.smtp.tls.enable) "${name}.smtp"
  ) cfg.activeAccounts;
  unsupportedAuthentications = lib.concatMap (
    name:
    let
      account = canonicalActiveAccounts.${name};
    in
    lib.optional (account.imap != null && account.imap.authentication != "login") "${name}.imap"
    ++ lib.optional (account.smtp != null && account.smtp.authentication != "login") "${name}.smtp"
  ) cfg.activeAccounts;
  invalidPrimaryAccounts = builtins.filter (
    name: canonicalActiveAccounts.${name}.primary != (name == cfg.defaultAccount)
  ) cfg.activeAccounts;
  mkSecretName = name: "email-${name}-password";

  mkAccount =
    name: definition:
    let
      identity = identities.${definition.identity};
      secretName = mkSecretName name;
    in
    {
      primary = name == cfg.defaultAccount;
      inherit (identity) address realName;
      inherit (definition)
        aliases
        folders
        imap
        smtp
        ;
      userName = if definition.userName == null then identity.address else definition.userName;
      passwordCommand = [
        "cat"
        config.sops.secrets.${secretName}.path
      ];
    };
in
{
  options.modules.core.email = {
    enable = lib.mkEnableOption "shared email account configuration";

    defaultAccount = lib.mkOption {
      type = lib.types.str;
      default = privateConfig.email.defaultAccount;
      description = "Default email account name.";
    };

    selectedAccounts = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ cfg.defaultAccount ];
      description = "Email account definitions selected for this profile.";
    };
    activeAccounts = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = lib.optionals cfg.enable (
        builtins.filter (
          name:
          builtins.hasAttr name config.accounts.email.accounts
          && config.accounts.email.accounts.${name}.enable
        ) cfg.selectedAccounts
      );
      readOnly = true;
      description = "Selected accounts whose canonical Home Manager account is enabled.";
    };

    definitions = lib.mkOption {
      type = lib.types.attrsOf accountType;
      default = privateConfig.email.accounts;
      readOnly = true;
      description = "Private account definitions before credential materialization.";
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = builtins.hasAttr cfg.defaultAccount cfg.definitions;
        message = "email: default account '${cfg.defaultAccount}' is not defined";
      }
      {
        assertion = undefinedSelectedAccounts == [ ];
        message =
          "email: undefined selected account definitions: "
          + lib.concatStringsSep ", " undefinedSelectedAccounts;
      }
      {
        assertion = cfg.selectedAccounts == [ ] || builtins.elem cfg.defaultAccount cfg.selectedAccounts;
        message = "email: default account '${cfg.defaultAccount}' must be selected";
      }
      {
        assertion = cfg.selectedAccounts == [ ] || builtins.elem cfg.defaultAccount cfg.activeAccounts;
        message = "email: default account '${cfg.defaultAccount}' must remain active";
      }
      {
        assertion = invalidNames == [ ];
        message = "email: invalid account names: ${lib.concatStringsSep ", " invalidNames}";
      }
      {
        assertion = builtins.all (account: account.imap != null || account.smtp != null) (
          builtins.attrValues canonicalActiveAccounts
        );
        message = "email: every active account needs at least one mail transport";
      }
      {
        assertion = insecureTransports == [ ];
        message =
          "email: password-backed LOGIN requires TLS on: " + lib.concatStringsSep ", " insecureTransports;
      }
      {
        assertion = unsupportedAuthentications == [ ];
        message =
          "email: unsupported canonical authentication (expected LOGIN) on: "
          + lib.concatStringsSep ", " unsupportedAuthentications;
      }
      {
        assertion = invalidPrimaryAccounts == [ ];
        message =
          "email: canonical primary flags disagree with defaultAccount on: "
          + lib.concatStringsSep ", " invalidPrimaryAccounts;
      }
    ];

    accounts.email.accounts = lib.mapAttrs mkAccount selectedDefinitions;

    sops.secrets = lib.mapAttrs' (
      name: _:
      lib.nameValuePair (mkSecretName name) {
        key = "email/accounts/${name}/password";
        mode = "0600";
      }
    ) activeDefinitions;
  };
}
