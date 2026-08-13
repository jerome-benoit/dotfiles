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
    local line
    line=''$(grep -A1 "''$2" "''$1" | tail -1)
    printf '%s\n' "''$line" | grep -qE '^[[:space:]]*version = "[^"]+"' \
      || fail "''$3: line after renovate marker is not 'version = ...' (workflow grep -A1 | tail -1)"
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
  grep -q 'url = "https://registry.npmjs.org/@earendil-works/pi-coding-agent[^"]*''${finalAttrs\.version}' "''$PI" \
    || fail "pi.nix: url line must contain \''${finalAttrs.version} placeholder (workflow sed substitution)"
  for a in src-hash npm-deps-hash; do
    grep -qE "''${HASH_RE}''${a}''$" "''$PI" || fail "pi.nix: @ci:''${a} not a trailing sha256 hash line"
  done
  # bind each anchor to its fetch block (src = pkgs.fetchzip { ... @ci:src-hash
  # ... }, npmDeps = pkgs.fetchNpmDeps { ... @ci:npm-deps-hash ... })
  awk '
    /src = pkgs\.fetchzip \{/ { in_src = 1 }
    /npmDeps = pkgs\.fetchNpmDeps \{/ { in_src = 0; in_npm = 1 }
    in_src && /@ci:src-hash/ { src_ok = 1 }
    in_npm && /@ci:npm-deps-hash/ { npm_ok = 1 }
    END { exit !(src_ok && npm_ok) }
  ' "''$PI" || fail "pi.nix: @ci:src-hash/@ci:npm-deps-hash not bound to their src/npmDeps blocks"

  # --- omp.nix ---
  OMP="''$DEV/omp.nix"
  check_version_after "''$OMP" '# renovate: datasource=github-releases depName=can1357/oh-my-pi' "omp.nix"
  EXPECTED_OMP_KEYS="darwin-arm64
  linux-arm64
  linux-x64"
  KEYS=''$(grep -oE '@ci:src-hash-[a-z0-9-]+' "''$OMP" | sed 's/@ci:src-hash-//' | LC_ALL=C sort -u)
  [ "''$KEYS" = "''$EXPECTED_OMP_KEYS" ] || fail "omp.nix: @ci:src-hash-<key> set mismatch: got=[''$KEYS]"
  for k in ''$KEYS; do
    # the workflow rewrites the physical line carrying @ci:src-hash-<key>: it
    # must be the hash assignment of the <key> map entry, not a swapped one
    grep -qE "\"''${k}\" = \"sha256-[A-Za-z0-9+/=]+\"; # @ci:src-hash-''${k}''$" "''$OMP" \
      || fail "omp.nix: @ci:src-hash-''${k} not bound to its ''${k} hash-map key"
  done

  # --- prime-agent.nix ---
  PA="''$DEV/prime-agent.nix"
  check_version_after "''$PA" '# renovate: datasource=github-releases depName=PrimeIntellect-ai/prime-agent' "prime-agent.nix"
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
      index($0, base "Src = pkgs.fetchzip {") { in_blk = 1 }
      in_blk && index($0, "@ci:npm-hash " k) { ok = 1 }
      END { exit !ok }
    ' "''$PA" || fail "prime-agent.nix: @ci:npm-hash ''${k} not bound to ''${base}Src block"
  done
  grep -q '# @ci:rlm-extra-packages ' "''$PA" || fail "prime-agent.nix: @ci:rlm-extra-packages marker missing"

  touch ''$out
''
