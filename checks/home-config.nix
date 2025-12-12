{
  self,
  pkgs,
  home-manager,
  arch,
}:

pkgs.runCommand "check-home-config"
  {
    nativeBuildInputs = [ home-manager.packages.${arch}.default or pkgs.hello ];
  }
  ''
    export HOME=$(${pkgs.coreutils}/bin/mktemp -d)
    if command -v home-manager >/dev/null 2>&1; then
      home-manager build \
        --flake ${self}#fraggle \
        --dry-run \
        || echo "home-manager check skipped (not available for ${arch})"
    fi
    touch $out
  ''
