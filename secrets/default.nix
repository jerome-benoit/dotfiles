# Absolute path bypasses Nix store copy; requires --impure.
# In pure eval (CI), $HOME is "" → falls back to placeholder values.
let
  home = builtins.getEnv "HOME";
  decFile = "${home}/.nix/secrets/personal.dec.json";
  placeholder = {
    username = "ci-placeholder";
    primaryEmail = "ci@placeholder.invalid";
    secondaryEmail = "ci@placeholder.invalid";
    workEmail = "ci@placeholder.invalid";
    gpg = {
      keyId = "0000000000000000";
      fingerprint = "0000000000000000000000000000000000000000";
    };
    telegram = {
      userId = "0";
    };
  };
in
if home != "" && builtins.pathExists decFile
then builtins.fromJSON (builtins.readFile decFile)
else if home == ""
then placeholder
else builtins.abort "Personal secrets not decrypted. Run 'make decrypt' first."
