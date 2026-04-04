{ self, pkgs }:

let
  currentSystem = pkgs.stdenv.hostPlatform.system;
  compatibleConfigs = pkgs.lib.filterAttrs (
    _: config: config.pkgs.stdenv.hostPlatform.system == currentSystem
  ) self.homeConfigurations;
in
pkgs.runCommandLocal "check-no-broken-symlinks" { } ''
  ${builtins.concatStringsSep "\n" (
    pkgs.lib.mapAttrsToList (name: config: ''
      broken=$(${pkgs.findutils}/bin/find ${config.activationPackage} -xtype l 2>/dev/null || true)
      if [ -n "$broken" ]; then
        echo "ERROR: Broken symlinks found in ${name}:" >&2
        echo "$broken" >&2
        exit 1
      fi
    '') compatibleConfigs
  )}
  touch $out
''
