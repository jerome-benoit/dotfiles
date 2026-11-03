{ self, pkgs }:

let
  currentSystem = pkgs.stdenv.hostPlatform.system;
  compatibleConfigs = pkgs.lib.filterAttrs (
    _: config: config.pkgs.stdenv.hostPlatform.system == currentSystem
  ) self.homeConfigurations;
  scan = pkgs.writeShellScript "scan-broken-symlinks" ''
    name=$1
    root=$2
    if ! broken=$(${pkgs.lib.getExe pkgs.findutils} "$root" -xtype l); then
      echo "ERROR: Cannot inspect symlinks in $name ($root)" >&2
      exit 1
    fi
    if [ -n "$broken" ]; then
      echo "ERROR: Broken symlinks found in $name:" >&2
      echo "$broken" >&2
      exit 1
    fi
  '';
in
pkgs.runCommandLocal "check-no-broken-symlinks" { } ''
  fixtures="$TMPDIR/symlinks with spaces"
  mkdir -p "$fixtures/sound" "$fixtures/broken"
  touch "$fixtures/sound/file"
  ln -s file "$fixtures/sound/link"
  ln -s missing "$fixtures/broken/dangling"
  ${scan} sound "$fixtures/sound"
  if ${scan} broken "$fixtures/broken" 2> "$fixtures/broken.err"; then
    echo "ERROR: Dangling symlink accepted" >&2
    exit 1
  fi
  [[ "$(< "$fixtures/broken.err")" == *"$fixtures/broken/dangling"* ]]
  if ${scan} missing "$fixtures/missing" 2> "$fixtures/missing.err"; then
    echo "ERROR: Failed symlink traversal accepted" >&2
    exit 1
  fi
  [[ "$(< "$fixtures/missing.err")" == *"$fixtures/missing"* ]]

  ${builtins.concatStringsSep "\n" (
    pkgs.lib.mapAttrsToList (name: config: ''
      ${scan} ${pkgs.lib.escapeShellArg name} ${pkgs.lib.escapeShellArg (toString config.activationPackage)}
    '') compatibleConfigs
  )}
  touch $out
''
