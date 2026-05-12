# Absolute path bypasses Nix store copy; requires --impure.
# In pure eval (CI), $HOME is "" → falls back to placeholder values.
let
  home = builtins.getEnv "HOME";
  decFile = "${home}/.nix/secrets/personal.dec.json";
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
      secondaryEmail = "ci@placeholder.invalid";
      domain = "personal.ci-placeholder.invalid";
      mail = {
        imapHost = "mail.ci-placeholder.invalid";
        smtpHost = "mail.ci-placeholder.invalid";
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
if home != "" && builtins.pathExists decFile then
  builtins.fromJSON (builtins.readFile decFile)
else if home == "" then
  placeholder
else
  builtins.abort "Personal secrets not decrypted. Run 'make decrypt' first."
