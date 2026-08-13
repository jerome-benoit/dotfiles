{ self, pkgs }:

# Validates the @ci: anchor contract that .github/workflows/fix-nix-hashes.yml
# relies on to rewrite hashes on renovate bumps. The workflow greps anchors with
# regexes (EOL-anchored for src-hash*); a renamed/moved/missing anchor makes it
# silently skip a hash. This check fails fast in `nix flake check` instead.
# Beyond presence, it binds each anchor to its semantic context (renovate
# marker -> next version line, url -> ${finalAttrs.version} placeholder,
# src-hash/npm-deps-hash -> their fetch blocks, omp keys -> map keys,
# prime-agent npm markers -> their variables), so swapped/misplaced anchors
# are caught too.
pkgs.runCommandLocal "check-ci-anchors" { nativeBuildInputs = [ pkgs.gawk ]; } ''
  set -euo pipefail
  DEV=${self}/home-manager/modules/development
  fail() { echo "ERROR: ''$1" >&2; exit 1; }
  HASH_RE='"sha256-[A-Za-z0-9+/=]+"; # @ci:'

  # the workflow extracts VERSION via `grep -A1 '<renovate marker>' | tail -1
  # | sed -n 's/.*"\([^"]*\)".*/\1/p'`: the line right after the marker must be
  # a version assignment, otherwise the extraction reads an unrelated line
  check_version_after() { # <file> <marker> <name>
    [ "''$(grep -cF "''$2" "''$1" || true)" -eq 1 ] \
      || fail "''$3: expected exactly one renovate marker line (workflow grep -A1 | tail -1 takes the last)"
    local line
    line=''$(grep -A1 "''$2" "''$1" | tail -1 || true)
    [ -n "''$line" ] \
      || fail "''$3: renovate marker not found, or not immediately followed by a version line (workflow grep -A1 | tail -1)"
    # the workflow sed is greedy ('s/.*"\([^"]*\)".*/\1/p'): it captures the LAST
    # quoted string on the line, so the version assignment must be clean up to EOL
    printf '%s\n' "''$line" | grep -qE '^[[:space:]]*version = "[^"]+";[[:space:]]*(#[^"]*)?$' \
      || fail "''$3: line after renovate marker is not a clean 'version = "...";' assignment (workflow sed greedy)"
    # the workflow sed would extract a ''${...} interpolation as-is and produce
    # an invalid URL at bump time
    if printf '%s\n' "''$line" | grep -q '\''${'; then
      fail "''$3: version must be a literal string, no \''${...} interpolation (workflow sed would extract it)"
    fi
  }

  # --- pi.nix ---
  PI="''$DEV/pi.nix"
  check_version_after "''$PI" '# renovate: datasource=npm depName=@earendil-works/pi-coding-agent' "pi.nix"
  grep -q 'url = "https://registry.npmjs.org/@earendil-works/pi-coding-agent' "''$PI" \
    || fail "pi.nix: url line (workflow URL_TEMPLATE) missing"
  # the workflow extracts URL_TEMPLATE via `sed -n 's/.*url = "\(.*\)".*/\1/p' | head -1`:
  # it matches 'url = "' anywhere, so exactly one such line must exist
  [ "''$(grep -c 'url = "' "''$PI")" -eq 1 ] \
    || fail "pi.nix: expected exactly one 'url = \"' line (workflow URL_TEMPLATE | head -1)"
  # the workflow substitutes ''${finalAttrs.version} in URL_TEMPLATE: the placeholder must be present
  grep -q 'url = "https://registry.npmjs.org/@earendil-works/pi-coding-agent/-/pi-coding-agent-''${finalAttrs\.version}\.tgz"' "''$PI" \
    || fail "pi.nix: url template must be .../-/pi-coding-agent-''${finalAttrs.version}.tgz (workflow URL_TEMPLATE)"
  for a in src-hash npm-deps-hash; do
    [ "''$(grep -cE "''${HASH_RE}''${a}''$" "''$PI" || true)" -eq 1 ] \
      || fail "pi.nix: expected exactly one @ci:''${a} trailing sha256 hash line"
  done
  # bind each anchor to its fetch block (src = pkgs.fetchzip { ... @ci:src-hash
  # ... }, npmDeps = pkgs.fetchNpmDeps { ... @ci:npm-deps-hash ... })
  awk '
    /src = pkgs\.fetchzip \{/ { in_src = 1 }
    /npmDeps = pkgs\.fetchNpmDeps \{/ { in_src = 0; in_npm = 1 }
    in_src && /^[[:space:]]*\};/ { in_src = 0 }
    in_npm && /^[[:space:]]*\};/ { in_npm = 0 }
    # anchor + hash on the same line, inside the block: a renamed anchor inside
    # the block with a fake EOL line outside would otherwise pass both greps
    in_src && /@ci:src-hash''$/ && /hash = "sha256-/ { src_ok = 1 }
    in_npm && /@ci:npm-deps-hash''$/ && /hash = "sha256-/ { npm_ok = 1 }
    END { exit !(src_ok && npm_ok) }
  ' "''$PI" || fail "pi.nix: @ci:src-hash/@ci:npm-deps-hash not bound to their src/npmDeps blocks"

  # --- omp.nix ---
  OMP="''$DEV/omp.nix"
  check_version_after "''$OMP" '# renovate: datasource=github-releases depName=can1357/oh-my-pi' "omp.nix"
  # the workflow hard-codes this download URL (fix-nix-hashes.yml): tag format
  # and asset name must keep the v''${finalAttrs.version}/omp-''${platformKey} shape
  grep -q 'url = "https://github.com/can1357/oh-my-pi/releases/download/v''${finalAttrs\.version}/omp-''${platformKey}"' "''$OMP" \
    || fail "omp.nix: url template must be .../releases/download/v\''${finalAttrs.version}/omp-\''${platformKey} (workflow hard-coded URL)"
  # keep in LC_ALL=C sorted order (the workflow derives keys dynamically; this exact
  # set is the intentional contract - adding a platform requires bumping it in the PR)
  EXPECTED_OMP_KEYS="darwin-arm64
  linux-arm64
  linux-x64"
  KEYS=''$(grep -oE '@ci:src-hash-[a-z0-9-]+' "''$OMP" | sed 's/@ci:src-hash-//' | LC_ALL=C sort -u || true)
  [ -n "''$KEYS" ] || fail "omp.nix: no @ci:src-hash-* anchors found"
  [ "''$KEYS" = "''$EXPECTED_OMP_KEYS" ] || fail "omp.nix: @ci:src-hash-<key> set mismatch: got=[''$KEYS]"
  # every map key must carry a marker, else the workflow (which derives keys from
  # markers only) would never rewrite that platform's hash
  MAPKEYS=''$(grep -oE '^[[:space:]]*"[a-z0-9-]+" = "sha256-' "''$OMP" | sed -E 's/^[[:space:]]*"([a-z0-9-]+)".*/\1/' | LC_ALL=C sort -u || true)
  [ "''$MAPKEYS" = "''$KEYS" ] || fail "omp.nix: hash-map keys without marker: got=[''$MAPKEYS] expected markers=[''$KEYS]"
  for k in ''$KEYS; do
    # the workflow rewrites the physical line carrying @ci:src-hash-<key>: it
    # must be the hash assignment of the <key> map entry, not a swapped one
    grep -qE "\"''${k}\" = \"sha256-[A-Za-z0-9+/=]+\"; # @ci:src-hash-''${k}''$" "''$OMP" \
      || fail "omp.nix: @ci:src-hash-''${k} not bound to its ''${k} hash-map key"
  done

  # --- prime-agent.nix ---
  PA="''$DEV/prime-agent.nix"
  check_version_after "''$PA" '# renovate: datasource=github-releases depName=PrimeIntellect-ai/prime-agent' "prime-agent.nix"
  # the workflow hard-codes this release URL (fix-nix-hashes.yml): keep the
  # v''${version}/prime-agent-''${version}.tgz shape
  grep -q 'url = "https://github.com/PrimeIntellect-ai/prime-agent/releases/download/v''${version}/prime-agent-''${version}\.tgz"' "''$PA" \
    || fail "prime-agent.nix: url template must be .../releases/download/v\''${version}/prime-agent-\''${version}.tgz (workflow hard-coded URL)"
  awk '
    /src = pkgs\.fetchzip \{/ { in_src = 1 }
    in_src && /^[[:space:]]*\};/ { in_src = 0 }
    in_src && /@ci:src-hash-prime-agent''$/ && /hash = "sha256-/ { src_ok = 1 }
    END { exit !src_ok }
  ' "''$PA" || fail "prime-agent.nix: @ci:src-hash-prime-agent not bound to the src fetch block (on a sha256 hash assignment)"
  # keep in LC_ALL=C sorted order; add a dep = bump this set + the case below in the PR
  EXPECTED_PA_KEYS="@silvia-odwyer/photon-node
  cmake-ts
  undici
  zeromq"
  VKEYS=''$(grep -oE '@ci:npm-version [^ ]+''$' "''$PA" | sed 's/@ci:npm-version //' | LC_ALL=C sort -u || true)
  HKEYS=''$(grep -oE '@ci:npm-hash [^ ]+''$' "''$PA" | sed 's/@ci:npm-hash //' | LC_ALL=C sort -u || true)
  [ -n "''$VKEYS" ] || fail "prime-agent.nix: no @ci:npm-version markers found"
  # two @ci:npm-hash markers on one line would let the workflow match the line for
  # the wrong dep (index() prefix match) while sort -u hides the duplicate: reject
  if grep -qE '@ci:npm-hash .*@ci:npm-hash' "''$PA"; then
    fail "prime-agent.nix: duplicate @ci:npm-hash markers on a single line"
  fi
  [ "''$VKEYS" = "''$HKEYS" ] || fail "prime-agent.nix: npm-version/npm-hash key mismatch: v=[''$VKEYS] h=[''$HKEYS]"
  [ "''$VKEYS" = "''$EXPECTED_PA_KEYS" ] || fail "prime-agent.nix: npm dep key set mismatch: got=[''$VKEYS]"
  for k in ''$VKEYS; do
    # each npm marker is bound to its dependency variable (<base>Version) and
    # its fetch block (<base>Src = pkgs.fetchzip { ... }): swapping markers
    # between two deps keeps the key sets equal but breaks the workflow rewrite
    case "''$k" in
      zeromq) base=zeromq ;;
      cmake-ts) base=cmakeTs ;;
      @silvia-odwyer/photon-node) base=photon ;;
      undici) base=undici ;;
      *) fail "prime-agent.nix: unexpected npm dep key ''$k" ;;
    esac
    grep -qE "^[[:space:]]*''${base}Version = \"[^\"]+\"; # @ci:npm-version ''${k}''$" "''$PA" \
      || fail "prime-agent.nix: @ci:npm-version ''${k} not bound to ''${base}Version"
    awk -v k="''$k" -v base="''$base" '
      index($0, base "Src = pkgs.fetchzip {") { in_blk = 1; next }
      in_blk && /^[[:space:]]*\};/ { in_blk = 0; next }
      in_blk && index($0, "@ci:npm-hash " k) && index($0, "hash = \"sha256-") { ok = 1 }
      END { exit !ok }
    ' "''$PA" || fail "prime-agent.nix: @ci:npm-hash ''${k} not bound to ''${base}Src block (on a sha256 hash assignment)"
  done
  # presence-only: semantic sync between the marker and kernelPython (pip -> nixpkgs
  # mapping) is a tracked follow-up - the workflow itself compares the marker against
  # upstream bootstrap.ts only, never against kernelPython
  grep -q '# @ci:rlm-extra-packages ' "''$PA" || fail "prime-agent.nix: @ci:rlm-extra-packages marker missing"

  touch ''$out
''
