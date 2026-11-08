# Absolute path bypasses Nix store copy; requires --impure.
# In pure eval (CI), $HOME is "" → falls back to placeholder values.
let
  home = builtins.getEnv "HOME";
  managedPrivateConfigFile = builtins.getEnv "NIX_PRIVATE_CONFIG_FILE";
  privateConfigFile =
    if managedPrivateConfigFile != "" then
      managedPrivateConfigFile
    else
      "${home}/.nix/secrets/private.dec.json";
  placeholder = {
    identity = {
      fullName = "ci-placeholder";
      username = "ci-user";
      gpg = {
        keyId = "0000000000000000";
        fingerprint = "0000000000000000000000000000000000000000";
      };
      telegram = {
        userId = "0";
      };
    };
    personal = {
      email = "ci@placeholder.invalid";
      domain = "personal.ci-placeholder.invalid";
    };
    email = {
      defaultAccount = "piment-noir";
      selectedAccounts = [
        "piment-noir"
        "work"
        "gmail"
      ];
      accounts = {
        piment-noir = {
          identity = "personal";
          folders = {
            inbox = "INBOX";
            sent = "Sent";
            drafts = "Drafts";
            trash = "Trash";
          };
          imap = {
            host = "imap.ci-placeholder.invalid";
            port = 993;
            authentication = "login";
            tls = {
              enable = true;
              useStartTls = false;
            };
          };
          smtp = {
            host = "smtp.ci-placeholder.invalid";
            port = 465;
            authentication = "login";
            tls = {
              enable = true;
              useStartTls = false;
            };
          };
          credential.type = "password";
        };
        gmail = {
          identity = "personal";
          address = "gmail@placeholder.invalid";
          folders = {
            inbox = "INBOX";
            sent = "SENT";
            drafts = "DRAFT";
            trash = "TRASH";
          };
          gmail = {
            userId = "me";
            tokenCommand = [
              "ortie"
              "token"
              "show"
              "-a"
              "gmail"
            ];
          };
        };
        work = {
          identity = "work";
          folders = {
            inbox = "INBOX";
            sent = "Sent Items";
            drafts = "Drafts";
            trash = "Deleted Items";
          };
          msgraph = {
            userId = "me";
            tokenCommand = [
              "ortie"
              "token"
              "show"
              "-a"
              "msgraph"
            ];
          };
        };
      };
      oauth.gmail.clientId = "ci-gmail.apps.googleusercontent.com";
    };
    work = {
      email = "ci@placeholder.invalid";
      employer = "ci-placeholder";
      jobTitle = "ci-placeholder";
      gheHostname = "ghe.ci-placeholder.invalid";
      username = "ci-user-work";
      tenantId = "00000000-0000-0000-0000-000000000000";
    };
    hosts = {
      server = "server.ci-placeholder.invalid";
    };
  };
in
if (managedPrivateConfigFile != "" || home != "") && builtins.pathExists privateConfigFile then
  builtins.fromJSON (builtins.readFile privateConfigFile)
else if managedPrivateConfigFile == "" && home == "" then
  placeholder
else
  builtins.abort "Private configuration not decrypted. Run 'make decrypt-private' first."
