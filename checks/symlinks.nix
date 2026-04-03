{ pkgs }:

name: activationPackage:

pkgs.runCommandLocal "check-symlinks-${name}" { } ''
  broken=$(${pkgs.findutils}/bin/find ${activationPackage} -xtype l 2>/dev/null || true)
  if [ -n "$broken" ]; then
    echo "ERROR: Broken symlinks found in ${name}:" >&2
    echo "$broken" >&2
    exit 1
  fi
  touch $out
''
