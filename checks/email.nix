{
  home-manager,
  pkgs,
  sops-nix,
}:

let
  lib = pkgs.lib;
  constants = import ../constants.nix;

  mkTransport = host: port: {
    inherit host port;
    authentication = "login";
    tls = {
      enable = true;
      useStartTls = false;
    };
  };

  mkAccount = folders: {
    identity = "personal";
    aliases = [ ];
    inherit folders;
    imap = mkTransport "imap.example.invalid" 993;
    smtp = mkTransport "smtp.example.invalid" 465;
    credential.type = "password";
  };

  privateConfig = {
    identity = {
      fullName = "Email Test";
      username = "email-test";
      gpg = {
        keyId = "0000000000000000";
        fingerprint = "0000000000000000000000000000000000000000";
      };
      telegram.userId = "0";
    };
    personal = {
      email = "email-test@example.invalid";
      domain = "example.invalid";
    };
    work = {
      email = "email-test-work@example.invalid";
      employer = "Test";
      jobTitle = "Test";
      gheHostname = "ghe.example.invalid";
      username = "email-test-work";
    };
    hosts.server = "server.example.invalid";
    email = {
      defaultAccount = "primary";
      accounts = {
        primary = mkAccount {
          inbox = "INBOX";
          sent = null;
          drafts = null;
          trash = "Trash";
        };
        disabled = mkAccount {
          inbox = "INBOX";
          sent = "Sent";
          drafts = "Drafts";
          trash = "Trash";
        };
        secondary =
          lib.recursiveUpdate
            (mkAccount {
              inbox = "INBOX";
              sent = "Sent";
              drafts = "Drafts";
              trash = "Trash";
            })
            {
              imap = {
                host = "starttls.example.invalid";
                port = 143;
                authentication = "login";
                tls = {
                  enable = true;
                  useStartTls = true;
                };
              };
              smtp = null;
            };
        unselected = mkAccount {
          inbox = "INBOX";
          sent = "Sent";
          drafts = "Drafts";
          trash = "Trash";
        };
      };
    };
  };

  configuration = home-manager.lib.homeManagerConfiguration {
    inherit pkgs;
    extraSpecialArgs = {
      inherit constants privateConfig;
    };
    modules = [
      sops-nix.homeManagerModules.sops
      ../home-manager/modules/core/constants.nix
      ../home-manager/modules/core/email.nix
      ../home-manager/modules/programs/himalaya.nix
      {
        home = {
          username = "email-test";
          homeDirectory = "/home/email-test";
          stateVersion = "26.05";
        };

        modules = {
          core.email = {
            enable = true;
            selectedAccounts = [
              "primary"
              "secondary"
              "disabled"
            ];
          };
          programs.himalaya.enable = true;
        };

        programs.himalaya.settings.downloads-dir = "/home/email-test/Downloads";

        accounts.email.accounts.disabled.enable = false;
        sops = {
          age.keyFile = "/home/email-test/.config/sops/age/keys.txt";
          defaultSopsFile = ../secrets/credentials.enc.yaml;
        };
      }
    ];
  };
  insecureConfiguration = configuration.extendModules {
    modules = [
      {
        accounts.email.accounts.primary.imap.tls.enable = lib.mkForce false;
      }
    ];
  };
  noTransportConfiguration = configuration.extendModules {
    modules = [
      {
        accounts.email.accounts.primary = {
          imap = lib.mkForce null;
          smtp = lib.mkForce null;
        };
      }
    ];
  };
  authenticationConfiguration = configuration.extendModules {
    modules = [
      {
        accounts.email.accounts.primary.imap.authentication = lib.mkForce "plain";
      }
    ];
  };
  primaryConfiguration = configuration.extendModules {
    modules = [
      {
        accounts.email.accounts = {
          primary.primary = lib.mkForce false;
          secondary.primary = lib.mkForce true;
        };
      }
    ];
  };

  credentialConfiguration = configuration.extendModules {
    modules = [
      {
        accounts.email.accounts.primary.passwordCommand = lib.mkForce [
          "${pkgs.coreutils}/bin/printf"
          "%s"
          "synthetic space $HOME;literal"
        ];
      }
    ];
  };
  overrideCredentialConfiguration = credentialConfiguration.extendModules {
    modules = [
      {
        accounts.email.accounts.primary.himalaya.settings = lib.genAttrs [ "imap" "smtp" ] (_: {
          sasl.login.password.command = lib.mkDefault [
            "${pkgs.coreutils}/bin/printf"
            "%s"
            "override space $HOME;literal"
          ];
        });
      }
    ];
  };
  smtpOnlyConfiguration = configuration.extendModules {
    modules = [ { accounts.email.accounts.primary.imap = lib.mkForce null; } ];
  };
  explicitMaildirConfiguration = smtpOnlyConfiguration.extendModules {
    modules = [ { accounts.email.accounts.primary.maildir = lib.mkDefault { path = "explicit"; }; } ];
  };

  cfg = configuration.config;
  canonicalAccounts = builtins.attrNames cfg.accounts.email.accounts;
  emailSecrets = builtins.filter (lib.hasPrefix "email-") (builtins.attrNames cfg.sops.secrets);
  himalayaConfig = cfg.xdg.configFile."himalaya/config.toml".source;
  insecureEvaluation = builtins.tryEval insecureConfiguration.activationPackage;
  noTransportEvaluation = builtins.tryEval noTransportConfiguration.activationPackage;
  authenticationEvaluation = builtins.tryEval authenticationConfiguration.activationPackage;
  primaryEvaluation = builtins.tryEval primaryConfiguration.activationPackage;
in
assert
  canonicalAccounts == [
    "disabled"
    "primary"
    "secondary"
  ];
assert
  cfg.modules.core.email.activeAccounts == [
    "primary"
    "secondary"
  ];
assert
  emailSecrets == [
    "email-primary-password"
    "email-secondary-password"
  ];
assert !insecureEvaluation.success;
assert !noTransportEvaluation.success;
assert !authenticationEvaluation.success;
assert !primaryEvaluation.success;
pkgs.runCommandLocal "check-email-accounts"
  {
    inherit himalayaConfig;
    credentialConfig = credentialConfiguration.config.xdg.configFile."himalaya/config.toml".source;
    overrideCredentialConfig =
      overrideCredentialConfiguration.config.xdg.configFile."himalaya/config.toml".source;
    smtpOnlyConfig = smtpOnlyConfiguration.config.xdg.configFile."himalaya/config.toml".source;
    explicitMaildirConfig =
      explicitMaildirConfiguration.config.xdg.configFile."himalaya/config.toml".source;
    nativeBuildInputs = [
      pkgs.himalaya
      pkgs.python3
    ];
  }
  ''
    himalaya -c "$himalayaConfig" --json account list >/dev/null
    python - "$himalayaConfig" "$smtpOnlyConfig" "$explicitMaildirConfig" <<'PY'
    import json
    import subprocess
    import sys
    import tomllib

    with open(sys.argv[1], "rb") as config_file:
        config = tomllib.load(config_file)

    assert config["downloads-dir"] == "/home/email-test/Downloads"
    assert config["envelope"]["list"] == {
        "datetime-local-tz": True,
        "page-size": 50,
    }
    assert set(config["accounts"]) == {"primary", "secondary"}

    primary = config["accounts"]["primary"]
    assert primary["default"] is True
    assert primary["mailbox"]["alias"] == {
        "inbox": "INBOX",
        "trash": "Trash",
    }
    assert primary["imap"]["server"] == "imaps://imap.example.invalid:993"
    assert primary["imap"]["starttls"] is False
    assert primary["smtp"]["server"] == "smtps://smtp.example.invalid:465"
    assert primary["smtp"]["starttls"] is False

    secondary = config["accounts"]["secondary"]
    assert secondary["default"] is False
    assert secondary["imap"]["server"] == "imap://starttls.example.invalid:143"
    assert secondary["imap"]["starttls"] is True
    assert "smtp" not in secondary

    for path, expected in [
        (sys.argv[2], {"smtp"}),
        (sys.argv[3], {"maildir", "smtp"}),
    ]:
        report = json.loads(subprocess.check_output(
            ["himalaya", "-c", path, "--json", "account", "list"], text=True
        ))
        account = next(a for a in report["accounts"] if a["name"] == "primary")
        assert set(account["backends"]) == expected, account
        print("SMTP_STORAGE_OK:", ",".join(sorted(expected)))
    PY
    python ${./email-credentials.py} "$credentialConfig" 'synthetic space $HOME;literal'
    python ${./email-credentials.py} "$overrideCredentialConfig" 'override space $HOME;literal'
    touch "$out"
  ''
