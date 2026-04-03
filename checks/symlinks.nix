{ self, pkgs }:

let
  configs = builtins.attrNames self.homeConfigurations;
in
pkgs.runCommand "check-no-broken-symlinks" { } ''
  ${builtins.concatStringsSep "\n" (
    map (name: ''
      result=$(${pkgs.nix}/bin/nix build ${self}#homeConfigurations.${name}.activationPackage \
        --no-link --print-out-paths 2>/dev/null || echo "")
      if [ -n "$result" ]; then
        broken=$(${pkgs.findutils}/bin/find "$result" -xtype l 2>/dev/null || true)
        if [ -n "$broken" ]; then
          echo "ERROR: Broken symlinks found in ${name}:" >&2
          echo "$broken" >&2
          exit 1
        fi
      fi
    '') configs
  )}
  touch $out
''
