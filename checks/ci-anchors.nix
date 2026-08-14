{ self, pkgs }:

# Validates the @ci: anchor contract that .github/workflows/fix-nix-hashes.yml
# relies on to rewrite hashes on renovate bumps. The workflow greps anchors with
# regexes and rewrites every matching line; a renamed/moved/missing anchor makes
# it silently skip a hash. This check fails fast in `nix flake check` instead.
# It requires active assignment lines (no leading '#'), EOL-anchored, bound to
# their fetch blocks, and exactly one occurrence per expected anchor - so a
# commented fake hash/url line, a duplicated marker, or a swapped binding is
# caught too.
pkgs.runCommandLocal "check-ci-anchors" { nativeBuildInputs = [ pkgs.gawk ]; } ''
  set -euo pipefail
  DEV=${self}/home-manager/modules/development
  fail() { echo "ERROR: ''$1" >&2; exit 1; }
  # active hash assignment lines only: no leading '#', anchor EOL
  HASH_LINE='^[[:space:]]*hash = "sha256-[A-Za-z0-9+/=]+"; # @ci:'

  # the workflow extracts VERSION via `grep -A1 '<renovate marker>' | tail -1
  # | sed -n 's/.*"\([^"]*\)".*/\1/p'` (greedy: last quoted string on the line)
  check_version_after() { # <file> <marker> <name>
    # renovate.json captures depName up to the next whitespace: require the marker
    # to end at EOL (a suffixed depName would silently stop renovate bumps)
    [ "''$(grep -cE "^[[:space:]]*''$2([[:space:]]+versioning=[^[:space:]]+)?[[:space:]]*$" "''$1" || true)" -eq 1 ] \
      || fail "''$3: expected exactly one renovate marker line ending at EOL (depName must not be suffixed)"
    # the workflow greps the marker as a substring: an impostor marker (suffixed
    # depName) followed by a plausible version line would be picked up by
    # grep -A1 | tail -1 and extract the wrong version
    [ "''$(grep -cF "''$2" "''$1" || true)" -eq 1 ] \
      || fail "''$3: expected exactly one renovate marker occurrence (workflow grep -A1 substring)"
    local line
    line=''$(grep -A1 "''$2" "''$1" | tail -1 || true)
    [ -n "''$line" ] \
      || fail "''$3: renovate marker not found, or not immediately followed by a version line (workflow grep -A1 | tail -1)"
    # the workflow sed captures the LAST quoted string: the version assignment
    # must be clean up to EOL with no stray quotes after it
    printf '%s\n' "''$line" | grep -qE '^[[:space:]]*version = "[^"]+";[[:space:]]*(#[^"]*)?$' \
      || fail "''$3: line after renovate marker is not a clean 'version = \"...\";' assignment (workflow sed greedy)"
    # the extracted version must be the FIRST version line of the file: a marker
    # moved above a nested package version (e.g. rlm in prime-agent.nix) would
    # make the workflow update the wrong release
    first=''$(grep -m1 -E '^[[:space:]]*version = "' "''$1" || true)
    [ -n "''$first" ] && [ "''$line" = "''$first" ] \
      || fail "''$3: version line after marker must be the package's top-level version"
    if printf '%s\n' "''$line" | grep -q '\''${'; then
      fail "''$3: version must be a literal string, no \''${...} interpolation (workflow sed would extract it)"
    fi
  }

  # --- pi.nix ---
  PI="''$DEV/pi.nix"
  check_version_after "''$PI" '# renovate: datasource=npm depName=@earendil-works/pi-coding-agent' "pi.nix"
  # the workflow extracts URL_TEMPLATE via `sed -n 's/.*url = "\(.*\)".*/\1/p' | head -1` on the
  # WHOLE file: the FIRST 'url = "' line must be the active src assignment (a
  # comment BEFORE it would be picked up; one AFTER it is harmless)
  [ "''$(grep -n 'url = "' "''$PI" | head -1 | cut -d: -f1)" = "''$(grep -nE '^[[:space:]]*url = "https://registry\.npmjs\.org/@earendil-works/pi-coding-agent/-/pi-coding-agent-\''${finalAttrs\.version}\.tgz";' "''$PI" | head -1 | cut -d: -f1 || true)" ] \
    || fail "pi.nix: first 'url = \"' line must be the active src assignment (workflow URL_TEMPLATE | head -1)"
  # url template bound to the src fetch block, clean up to EOL (workflow:
  # sed -n 's/.*url = "\(.*\)".*/\1/p' | head -1 - greedy, matches anywhere)
  awk -v pat='url = "https://registry.npmjs.org/@earendil-works/pi-coding-agent/-/pi-coding-agent-''${finalAttrs.version}.tgz";' '
    /^[[:space:]]*src = pkgs\.fetchzip / { in_src = 1; next }
    in_src && /^[[:space:]]*\};/ { in_src = 0; next }
    in_src && index($0, pat) && $0 ~ /^[[:space:]]*url = / && $0 ~ /;[[:space:]]*(#[^"]*)?$/ { url_ok = 1 }
    END { exit !url_ok }
  ' "''$PI" || fail "pi.nix: url template must be .../-/pi-coding-agent-\''${finalAttrs.version}.tgz (workflow URL_TEMPLATE)"
  for a in src-hash npm-deps-hash; do
    # exactly one canonical anchor, and count ALL occurrences (workflow matches
    # npm-deps-hash without EOL, so a noncanonical duplicate would be rewritten)
    [ "''$(grep -cE "''${HASH_LINE}''${a}''$" "''$PI" || true)" -eq 1 ] \
      || fail "pi.nix: expected exactly one @ci:''${a} trailing sha256 hash line"
    [ "''$(grep -cF "@ci:''${a}" "''$PI" || true)" -eq 1 ] \
      || fail "pi.nix: expected exactly one @ci:''${a} marker anywhere (workflow matches non-EOL)"
  done
  # the workflow regenerates and copies ./pi-package-lock.json: the module must
  # consume exactly that lock file (a refactor to another lock would stale the npm hash)
  grep -qF './pi-package-lock.json' "''$PI" \
    || fail "pi.nix: ./pi-package-lock.json reference missing (workflow copies the regenerated lock)"
  # bind each anchor to its fetch block, on the same active hash line
  awk '
    /^[[:space:]]*src = pkgs\.fetchzip / { in_src = 1 }
    /^[[:space:]]*npmDeps = pkgs\.fetchNpmDeps / { in_src = 0; in_npm = 1 }
    in_src && /^[[:space:]]*\};/ { in_src = 0 }
    in_npm && /^[[:space:]]*\};/ { in_npm = 0 }
    in_src && /^[[:space:]]*hash = "sha256-[A-Za-z0-9+/=]+"; # @ci:src-hash''$/ { src_ok = 1 }
    in_npm && /^[[:space:]]*hash = "sha256-[A-Za-z0-9+/=]+"; # @ci:npm-deps-hash''$/ { npm_ok = 1 }
    END { exit !(src_ok && npm_ok) }
  ' "''$PI" || fail "pi.nix: @ci:src-hash/@ci:npm-deps-hash not bound to their src/npmDeps blocks"

  # --- omp.nix ---
  OMP="''$DEV/omp.nix"
  check_version_after "''$OMP" '# renovate: datasource=github-releases depName=can1357/oh-my-pi' "omp.nix"
  # the workflow hard-codes this download URL (fix-nix-hashes.yml): keep the
  # v''${finalAttrs.version}/omp-''${platformKey} shape, bound to the src fetch block
  awk -v pat='url = "https://github.com/can1357/oh-my-pi/releases/download/v''${finalAttrs.version}/omp-''${platformKey}";' '
    /^[[:space:]]*src = pkgs\.fetchurl / { in_src = 1; next }
    in_src && /^[[:space:]]*\};/ { in_src = 0; next }
    in_src && index($0, pat) && $0 ~ /^[[:space:]]*url = / && $0 ~ /;[[:space:]]*(#[^"]*)?$/ { url_ok = 1 }
    in_src && $0 ~ /^[[:space:]]*hash = hashes\./ && index($0, "hash = hashes.''${platformKey};") { hash_ref_ok = 1 }
    END { exit !(url_ok && hash_ref_ok) }
  ' "''$OMP" || fail "omp.nix: src fetch block must have the v\''${finalAttrs.version}/omp-\''${platformKey} url and hash = hashes.<key> (workflow hard-coded URL)"
  # keep in LC_ALL=C sorted order (the workflow derives keys dynamically; this exact
  # set is the intentional contract - adding a platform requires bumping it in the PR)
  EXPECTED_OMP_KEYS="darwin-arm64
  linux-arm64
  linux-x64"
  KEYS=''$(grep -oE '@ci:src-hash-[a-z0-9-]+' "''$OMP" | sed 's/@ci:src-hash-//' | LC_ALL=C sort -u || true)
  [ -n "''$KEYS" ] || fail "omp.nix: no @ci:src-hash-* anchors found"
  [ "''$KEYS" = "''$EXPECTED_OMP_KEYS" ] || fail "omp.nix: @ci:src-hash-<key> set mismatch: got=[''$KEYS] expected=[''$EXPECTED_OMP_KEYS]"
  # every hash-map key must carry a marker (workflow derives keys from markers
  # only, an unmarked map entry would never be rewritten), bound to the hashes block
  MAPKEYS=''$(awk '
    /^[[:space:]]*hashes = \{/ { in_map = 1 }
    in_map && /^[[:space:]]*\};/ { in_map = 0 }
    in_map && /^[[:space:]]*"[a-z0-9-]+" = "sha256-/ { match($0, /"([a-z0-9-]+)" = /, m); print m[1] }
  ' "''$OMP" | LC_ALL=C sort -u || true)
  [ "''$MAPKEYS" = "''$KEYS" ] || fail "omp.nix: hash-map keys without marker: got=[''$MAPKEYS] expected markers=[''$KEYS]"
  for k in ''$KEYS; do
    # exactly one active assignment per key (workflow rewrites every matching line)
    [ "''$(grep -cE "^[[:space:]]*\"''${k}\" = \"sha256-[A-Za-z0-9+/=]+\"; # @ci:src-hash-''${k}''$" "''$OMP" || true)" -eq 1 ] \
      || fail "omp.nix: expected exactly one @ci:src-hash-''${k} bound to its ''${k} hash-map key"
    # workflow matches EVERY line ending with the suffix: count globally
    [ "''$(grep -cE "@ci:src-hash-''${k}''$" "''$OMP" || true)" -eq 1 ] \
      || fail "omp.nix: expected exactly one @ci:src-hash-''${k} marker line anywhere"
  done

  # --- prime-agent.nix ---
  PA="''$DEV/prime-agent.nix"
  check_version_after "''$PA" '# renovate: datasource=github-releases depName=PrimeIntellect-ai/prime-agent' "prime-agent.nix"
  # the workflow hard-codes this release URL (fix-nix-hashes.yml): keep the
  # v''${version}/prime-agent-''${version}.tgz shape, bound to the src fetch block
  awk -v pat='url = "https://github.com/PrimeIntellect-ai/prime-agent/releases/download/v''${version}/prime-agent-''${version}.tgz";' '
    /^[[:space:]]*src = pkgs\.fetchzip / { in_src = 1; next }
    in_src && /^[[:space:]]*\};/ { in_src = 0; next }
    in_src && index($0, pat) && $0 ~ /^[[:space:]]*url = / && $0 ~ /;[[:space:]]*(#[^"]*)?$/ { url_ok = 1 }
    in_src && /^[[:space:]]*hash = "sha256-[A-Za-z0-9+/=]+"; # @ci:src-hash-prime-agent''$/ { src_hash_ok = 1 }
    END { exit !(url_ok && src_hash_ok) }
  ' "''$PA" || fail "prime-agent.nix: src fetch block must have the v\''${version}/prime-agent-\''${version}.tgz url and @ci:src-hash-prime-agent hash"
  # workflow matches EVERY line ending with this marker: exactly one active occurrence
  [ "''$(grep -cE "^[[:space:]]*hash = \"sha256-[A-Za-z0-9+/=]+\"; # @ci:src-hash-prime-agent''$" "''$PA" || true)" -eq 1 ] \
    || fail "prime-agent.nix: expected exactly one @ci:src-hash-prime-agent hash line"
  [ "''$(grep -cF '@ci:src-hash-prime-agent' "''$PA" || true)" -eq 1 ] \
    || fail "prime-agent.nix: expected exactly one @ci:src-hash-prime-agent marker occurrence (workflow suffix match)"
  # keep in LC_ALL=C sorted order; add a dep = bump this set + the case below in the PR
  EXPECTED_PA_KEYS="@silvia-odwyer/photon-node
  cmake-ts
  undici
  zeromq"
  VKEYS=''$(grep -oE '@ci:npm-version [^ ]+''$' "''$PA" | sed 's/@ci:npm-version //' | LC_ALL=C sort -u || true)
  HKEYS=''$(grep -oE '@ci:npm-hash [^ ]+''$' "''$PA" | sed 's/@ci:npm-hash //' | LC_ALL=C sort -u || true)
  [ -n "''$VKEYS" ] || fail "prime-agent.nix: no @ci:npm-version markers found"
  # two @ci:npm-hash markers on one line would let the workflow match the line for
  # the wrong dep (index() substring match) while sort -u hides the duplicate: reject
  if grep -qE '@ci:npm-hash .*@ci:npm-hash' "''$PA"; then
    fail "prime-agent.nix: duplicate @ci:npm-hash markers on a single line"
  fi
  [ "''$VKEYS" = "''$HKEYS" ] || fail "prime-agent.nix: npm-version/npm-hash key mismatch: v=[''$VKEYS] h=[''$HKEYS]"
  [ "''$VKEYS" = "''$EXPECTED_PA_KEYS" ] || fail "prime-agent.nix: npm dep key set mismatch: got=[''$VKEYS]"
  for k in ''$VKEYS; do
    # each npm marker is bound to its dependency variable (<base>Version), its
    # fetch block (<base>Src = pkgs.fetchzip { ... }), and its registry url
    case "''$k" in
      zeromq) base=zeromq ;;
      cmake-ts) base=cmakeTs ;;
      @silvia-odwyer/photon-node) base=photon ;;
      undici) base=undici ;;
      *) fail "prime-agent.nix: unexpected npm dep key ''$k" ;;
    esac
    [ "''$(grep -cE "^[[:space:]]*''${base}Version = \"[^\"]+\"; # @ci:npm-version ''${k}''$" "''$PA" || true)" -eq 1 ] \
      || fail "prime-agent.nix: expected exactly one @ci:npm-version ''${k} bound to ''${base}Version"
    # workflow index() rewrites EVERY line ending with the marker: exactly one
    # workflow index($0, "@ci:npm-version " key) matches substrings: count those too
    [ "''$(grep -cF "@ci:npm-version ''${k}" "''$PA" || true)" -eq 1 ] \
      || fail "prime-agent.nix: expected exactly one @ci:npm-version ''${k} marker occurrence (workflow index() substring)"
    awk -v k="''$k" -v base="''$base" -v pat="https://registry.npmjs.org/''${k}/-/''${k##*/}-\''${''${base}Version}.tgz" '
      $0 ~ ("^[[:space:]]*" base "Src = pkgs.fetchzip ") { in_blk = 1; next }
      in_blk && /^[[:space:]]*\};/ { in_blk = 0; next }
      in_blk && index($0, pat) && $0 ~ /^[[:space:]]*url = / { url_ok = 1 }
      in_blk && $0 ~ /^[[:space:]]*hash = "sha256-[A-Za-z0-9+/=]+"/ && $0 ~ ("@ci:npm-hash " k "$") { hash_ok = 1 }
      END { exit !(url_ok && hash_ok) }
    ' "''$PA" || fail "prime-agent.nix: @ci:npm-hash ''${k} / url not bound to ''${base}Src block (active hash assignment)"
    [ "''$(grep -cE "^[[:space:]]*hash = \"sha256-[A-Za-z0-9+/=]+\"; # @ci:npm-hash ''${k}''$" "''$PA" || true)" -eq 1 ] \
      || fail "prime-agent.nix: expected exactly one @ci:npm-hash ''${k} hash line"
    [ "''$(grep -cF "@ci:npm-hash ''${k}" "''$PA" || true)" -eq 1 ] \
      || fail "prime-agent.nix: expected exactly one @ci:npm-hash ''${k} marker occurrence (workflow index() substring)"
  done
  # presence-only: semantic sync between the marker and kernelPython (pip -> nixpkgs
  # mapping) is a tracked follow-up - the workflow itself compares the marker against
  # upstream bootstrap.ts only, never against kernelPython. Require a non-empty list.
  [ "''$(grep -cE '# @ci:rlm-extra-packages [[:alnum:]-]+' "''$PA" || true)" -eq 1 ] \
    || fail "prime-agent.nix: expected exactly one non-empty @ci:rlm-extra-packages marker (workflow head -1)"

  # the workflow must still contain its exact rewrite patterns (bot C24): if a
  # pattern is renamed or dropped there, the bump silently skips the hash
  WF=''$DEV/../../../.github/workflows/fix-nix-hashes.yml
  # renovate.json must still recognize the markers (bot C32): a changed custom
  # manager pattern silently stops the bumps this automation relies on
  RJ=''$DEV/../../../renovate.json
  grep -qF '"customManagers"' "''$RJ" && grep -qF '"managerFilePatterns"' "''$RJ" \
    || fail "renovate.json: customManagers/managerFilePatterns missing (renovate would stop bumping)"
  grep -qF '"managerFilePatterns": ["/\\.nix$/"]' "''$RJ" \
    || fail "renovate.json: managerFilePatterns must match /\\.nix$/ (renovate would stop scanning)"
  grep -qF '"#\\s*renovate:' "''$RJ" \
    || fail "renovate.json: matchStrings pattern missing (renovate would stop bumping)"
  grep -qF '(?<datasource>' "''$RJ" && grep -qF '(?<depName>' "''$RJ" \
    || fail "renovate.json: matchStrings named groups missing (renovate would stop bumping)"
  grep -qF '(?<currentValue>' "''$RJ" && grep -qF 'depName=' "''$RJ" \
    || fail "renovate.json: currentValue group or depName= missing (renovate would stop bumping)"
  grep -qF '(?<versioning>' "''$RJ" && grep -qF '"versioningTemplate"' "''$RJ" \
    || fail "renovate.json: versioning group/template missing (renovate would stop bumping)"
  grep -qF '\\n[^\\n]*version' "''$RJ" \
    || fail "renovate.json: marker-to-version adjacency missing (renovate would stop bumping)"
  grep -qF 'version\\s' "''$RJ" && grep -qF '\"(?<currentValue>' "''$RJ" \
    || fail "renovate.json: version capture pattern missing (renovate would stop bumping)"
  for pat in '/@ci:src-hash$' '/@ci:npm-deps-hash/' '/@ci:src-hash-prime-agent$' '"@ci:npm-version " key' '"@ci:npm-hash " key' '@ci:rlm-extra-packages' '@ci:src-hash-[a-z0-9-]+' '@ci:npm-version .+' 'grep -A1' 'sub(/"sha256-[^"]*"/' '.*"\([^"]*\)".*/\1/p' '.*url = "\(.*\)".*/\1/p' 'releases/download/v''${VERSION}/omp-''${key}' 'v''${VERSION}/prime-agent-''${VERSION}.tgz' "depName=@earendil-works/pi-coding-agent'" "depName=can1357/oh-my-pi'" "depName=PrimeIntellect-ai/prime-agent'" "@ci:src-hash-'\""; do
    grep -qF "''$pat" "''$WF" || fail "fix-nix-hashes.yml: missing rewrite pattern ''$pat (contract drift)"
  done

  touch ''$out
''
