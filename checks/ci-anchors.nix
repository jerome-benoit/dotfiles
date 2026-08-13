{ self, pkgs }:

# Validates the @ci: anchor contract that .github/workflows/fix-nix-hashes.yml
# relies on to rewrite hashes on renovate bumps. The workflow greps anchors with
# regexes (EOL-anchored for src-hash*); a renamed/moved/missing anchor makes it
# silently skip a hash. This check fails fast in `nix flake check` instead.
pkgs.runCommandLocal "check-ci-anchors" { nativeBuildInputs = [ pkgs.gawk ]; } ''
  set -euo pipefail
  DEV=${self}/home-manager/modules/development
  fail() { echo "ERROR: ''$1" >&2; exit 1; }
  HASH_RE='"sha256-[A-Za-z0-9+/=]+"; # @ci:'

  # --- pi.nix ---
  PI="''$DEV/pi.nix"
  grep -q '# renovate: datasource=npm depName=@earendil-works/pi-coding-agent' "''$PI" \
    || fail "pi.nix: renovate npm marker missing"
  grep -q 'url = "https://registry.npmjs.org/@earendil-works/pi-coding-agent' "''$PI" \
    || fail "pi.nix: url line (workflow URL_TEMPLATE) missing"
  # the workflow extracts URL_TEMPLATE via `sed -n 's/.*url = "\(.*\)".*/\1/p' | head -1`:
  # it matches 'url = "' anywhere, so exactly one such line must exist
  [ "''$(grep -c 'url = "' "''$PI")" -eq 1 ] \
    || fail "pi.nix: expected exactly one 'url = \"' line (workflow URL_TEMPLATE | head -1)"
  for a in src-hash npm-deps-hash; do
    grep -qE "''${HASH_RE}''${a}''$" "''$PI" || fail "pi.nix: @ci:''${a} not a trailing sha256 hash line"
  done

  # --- omp.nix ---
  OMP="''$DEV/omp.nix"
  grep -q '# renovate: datasource=github-releases depName=can1357/oh-my-pi' "''$OMP" \
    || fail "omp.nix: renovate github-releases marker missing"
  EXPECTED_OMP_KEYS="darwin-arm64
  linux-arm64
  linux-x64"
  KEYS=''$(grep -oE '@ci:src-hash-[a-z0-9-]+' "''$OMP" | sed 's/@ci:src-hash-//' | LC_ALL=C sort -u)
  [ "''$KEYS" = "''$EXPECTED_OMP_KEYS" ] || fail "omp.nix: @ci:src-hash-<key> set mismatch: got=[''$KEYS]"
  for k in ''$KEYS; do
    grep -qE "''${HASH_RE}src-hash-''${k}''$" "''$OMP" || fail "omp.nix: @ci:src-hash-''${k} not a trailing sha256 hash line"
  done

  # --- prime-agent.nix ---
  PA="''$DEV/prime-agent.nix"
  grep -q '# renovate: datasource=github-releases depName=PrimeIntellect-ai/prime-agent' "''$PA" \
    || fail "prime-agent.nix: renovate marker missing"
  grep -qE "''${HASH_RE}src-hash-prime-agent''$" "''$PA" || fail "prime-agent.nix: @ci:src-hash-prime-agent not a trailing sha256 hash line"
  EXPECTED_PA_KEYS="@silvia-odwyer/photon-node
  cmake-ts
  undici
  zeromq"
  VKEYS=''$(grep -oE '@ci:npm-version [^ ]+''$' "''$PA" | sed 's/@ci:npm-version //' | LC_ALL=C sort -u)
  HKEYS=''$(grep -oE '@ci:npm-hash [^ ]+''$' "''$PA" | sed 's/@ci:npm-hash //' | LC_ALL=C sort -u)
  [ "''$VKEYS" = "''$HKEYS" ] || fail "prime-agent.nix: npm-version/npm-hash key mismatch: v=[''$VKEYS] h=[''$HKEYS]"
  [ "''$VKEYS" = "''$EXPECTED_PA_KEYS" ] || fail "prime-agent.nix: npm dep key set mismatch: got=[''$VKEYS]"
  for k in ''$VKEYS; do
    grep -qE "\"[^\"]+\"; # @ci:npm-version ''${k}''$" "''$PA" || fail "prime-agent.nix: @ci:npm-version ''${k} not a trailing version line"
    grep -qE "''${HASH_RE}npm-hash ''${k}''$" "''$PA" || fail "prime-agent.nix: @ci:npm-hash ''${k} not a trailing sha256 hash line"
  done
  grep -q '# @ci:rlm-extra-packages ' "''$PA" || fail "prime-agent.nix: @ci:rlm-extra-packages marker missing"

  touch ''$out
''
