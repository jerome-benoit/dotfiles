# Absolute path bypasses Nix store copy; requires --impure.
# In pure eval (CI), $HOME is "" → falls back to placeholder values.
let
  home = builtins.getEnv "HOME";
  privateConfigFile = "${home}/.nix/secrets/private.dec.json";
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
      accounts.piment-noir = {
        identity = "personal";
        aliases = [ "secondary@placeholder.invalid" ];
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
    };
    work = {
      email = "ci@placeholder.invalid";
      employer = "ci-placeholder";
      jobTitle = "ci-placeholder";
      gheHostname = "ghe.ci-placeholder.invalid";
      username = "ci-user-work";
    };
    hosts = {
      server = "server.ci-placeholder.invalid";
    };
  };
in
if home != "" && builtins.pathExists privateConfigFile then
  builtins.fromJSON (builtins.readFile privateConfigFile)
else if home == "" then
  placeholder
else
  builtins.abort "Private configuration not decrypted. Run 'make decrypt-private' first."
