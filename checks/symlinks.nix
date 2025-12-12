{ self, pkgs }:

pkgs.runCommand "check-no-broken-symlinks" { } ''
  result=$(${pkgs.nix}/bin/nix build ${self}#homeConfigurations.fraggle.activationPackage \
    --no-link --print-out-paths 2>/dev/null || echo "")
  if [ -n "$result" ]; then
    broken=$(${pkgs.findutils}/bin/find "$result" -xtype l 2>/dev/null || true)
    if [ -n "$broken" ]; then
      echo "ERROR: Broken symlinks found:" >&2
      echo "$broken" >&2
      exit 1
    fi
  fi
  touch $out
''
