#!/usr/bin/env bash
set -euo pipefail

PIN_DIR_REL=home-manager/modules/development/pins
PI_PIN_REL=$PIN_DIR_REL/pi.json
OMP_PIN_REL=$PIN_DIR_REL/omp.json
PRIME_PIN_REL=$PIN_DIR_REL/prime-agent.json
PI_LOCK_REL=home-manager/modules/development/pi-package-lock.json
FIX_WORKFLOW_REL=.github/workflows/fix-nix-hashes.yml
CHECK_WORKFLOW_REL=.github/workflows/check.yml
SCRIPT_REL=scripts/fix-nix-hashes.sh

PIN_MANAGER_PATTERN='/^home-manager/modules/development/pins/(pi|omp|prime-agent)\.json$/'
PIN_MANAGER_MATCH='"renovate"\s*:\s*"datasource=(?<datasource>\S+)\s+depName=(?<depName>\S+)(\s+versioning=(?<versioning>\S+))?"\s*,\s*\n\s*"version"\s*:\s*"(?<currentValue>[^"]+)"'
VERSIONING_TEMPLATE='{{#if versioning}}{{{versioning}}}{{else}}semver{{/if}}'
HASH_PATTERN='^sha256-[A-Za-z0-9+/=]+$'

fail() {
  echo "ERROR: $1" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null || fail "$1 is required"
}

render_url() {
  local template=$1 version=$2 key=${3:-}
  local rendered=${template//\{version\}/$version}
  rendered=${rendered//\{key\}/$key}
  printf '%s\n' "$rendered"
}

validate_pin_files() {
  local pi=$1 omp=$2 prime=$3 expected_lock_rel

  jq -e --arg hash "$HASH_PATTERN" '
    type == "object"
    and (keys == ["lockFile", "npmDepsHash", "renovate", "src", "version"])
    and (.renovate == "datasource=npm depName=@earendil-works/pi-coding-agent")
    and (.version | type == "string" and length > 0)
    and (.lockFile == "pi-package-lock.json")
    and (.npmDepsHash | test($hash))
    and (.src | keys == ["hash", "urlTemplate"])
    and (.src.hash | test($hash))
    and (.src.urlTemplate == "https://registry.npmjs.org/@earendil-works/pi-coding-agent/-/pi-coding-agent-{version}.tgz")
  ' "$pi" >/dev/null || fail "invalid Pi pin contract"
  expected_lock_rel=${PIN_DIR_REL%/pins}/$(jq -r .lockFile "$pi")
  [ "$PI_LOCK_REL" = "$expected_lock_rel" ] \
    || fail "Pi updater lock destination differs from the effective module lock"

  jq -e --arg hash "$HASH_PATTERN" '
    type == "object"
    and (keys == ["hashes", "renovate", "urlTemplate", "version"])
    and (.renovate == "datasource=github-releases depName=can1357/oh-my-pi")
    and (.version | type == "string" and length > 0)
    and (.urlTemplate == "https://github.com/can1357/oh-my-pi/releases/download/v{version}/omp-{key}")
    and (.hashes | keys == ["darwin-arm64", "linux-arm64", "linux-x64"])
    and ([.hashes[] | test($hash)] | all)
  ' "$omp" >/dev/null || fail "invalid OMP pin contract"

  jq -e --arg hash "$HASH_PATTERN" '
    type == "object"
    and (keys == ["npm", "renovate", "rlmExtraPackages", "snapshotRequirement", "src", "version"])
    and (.renovate == "datasource=github-releases depName=PrimeIntellect-ai/prime-agent")
    and (.version | type == "string" and length > 0)
    and (.snapshotRequirement | type == "string" and length > 0)
    and (.src | keys == ["hash", "urlTemplate"])
    and (.src.hash | test($hash))
    and (.src.urlTemplate == "https://github.com/PrimeIntellect-ai/prime-agent/releases/download/v{version}/prime-agent-{version}.tgz")
    and (.npm | keys == ["@silvia-odwyer/photon-node", "cmake-ts", "undici", "zeromq"])
    and (.npm["@silvia-odwyer/photon-node"].urlTemplate == "https://registry.npmjs.org/@silvia-odwyer/photon-node/-/photon-node-{version}.tgz")
    and (.npm["cmake-ts"].urlTemplate == "https://registry.npmjs.org/cmake-ts/-/cmake-ts-{version}.tgz")
    and (.npm.undici.urlTemplate == "https://registry.npmjs.org/undici/-/undici-{version}.tgz")
    and (.npm.zeromq.urlTemplate == "https://registry.npmjs.org/zeromq/-/zeromq-{version}.tgz")
    and ([.npm[] | keys == ["hash", "urlTemplate", "version"]] | all)
    and ([.npm[].hash | test($hash)] | all)
    and ([.npm[].version | type == "string" and length > 0] | all)
    and (.rlmExtraPackages | type == "array" and length > 0)
    and ([.rlmExtraPackages[] | type == "string" and test("^[a-z0-9-]+$")] | all)
    and (.rlmExtraPackages == (.rlmExtraPackages | sort | unique))
  ' "$prime" >/dev/null || fail "invalid Prime Agent pin contract"
}

validate_effective_contract() {
  local root=$1 effective=$2
  local pi=$root/$PI_PIN_REL omp=$root/$OMP_PIN_REL prime=$root/$PRIME_PIN_REL
  local version template key expected actual

  version=$(jq -r .version "$pi")
  template=$(jq -r .src.urlTemplate "$pi")
  expected=$(render_url "$template" "$version")
  actual=$(jq -r .pi.src.url "$effective")
  [ "$actual" = "$expected" ] || fail "Pi effective source URL does not consume its pin"
  jq -e --slurpfile pin "$pi" '
    .pi.version == $pin[0].version
    and .pi.src.hash == $pin[0].src.hash
    and .pi.npmDepsHash == $pin[0].npmDepsHash
    and .pi.lockFile == $pin[0].lockFile
  ' "$effective" >/dev/null || fail "Pi effective values do not consume their pin"

  version=$(jq -r .version "$omp")
  jq -e --slurpfile pin "$omp" \
    '.omp.version == $pin[0].version' "$effective" >/dev/null \
    || fail "OMP effective version does not consume its pin"
  while IFS= read -r key; do
    template=$(jq -r .urlTemplate "$omp")
    expected=$(render_url "$template" "$version" "$key")
    actual=$(jq -r --arg key "$key" '.omp.sources[$key].url' "$effective")
    [ "$actual" = "$expected" ] || fail "OMP effective URL does not consume pin key $key"
    jq -e --arg key "$key" --slurpfile pin "$omp" \
      '.omp.sources[$key].hash == $pin[0].hashes[$key]' "$effective" >/dev/null \
      || fail "OMP effective hash does not consume pin key $key"
  done < <(jq -r '.hashes | keys[]' "$omp")

  version=$(jq -r .version "$prime")
  template=$(jq -r .src.urlTemplate "$prime")
  expected=$(render_url "$template" "$version")
  actual=$(jq -r .primeAgent.src.url "$effective")
  [ "$actual" = "$expected" ] || fail "Prime Agent effective source URL does not consume its pin"
  jq -e --slurpfile pin "$prime" '
    .primeAgent.version == $pin[0].version
    and .primeAgent.src.hash == $pin[0].src.hash
    and .primeAgent.rlmExtraPackages == $pin[0].rlmExtraPackages
    and .primeAgent.snapshotRequirement == $pin[0].snapshotRequirement
  ' "$effective" >/dev/null || fail "Prime Agent effective values do not consume their pin"

  while IFS= read -r key; do
    version=$(jq -r --arg key "$key" '.npm[$key].version' "$prime")
    template=$(jq -r --arg key "$key" '.npm[$key].urlTemplate' "$prime")
    expected=$(render_url "$template" "$version")
    actual=$(jq -r --arg key "$key" '.primeAgent.npm[$key].src.url' "$effective")
    [ "$actual" = "$expected" ] || fail "Prime Agent npm URL does not consume pin key $key"
    jq -e --arg key "$key" --slurpfile pin "$prime" '
      .primeAgent.npm[$key].version == $pin[0].npm[$key].version
      and .primeAgent.npm[$key].src.hash == $pin[0].npm[$key].hash
    ' "$effective" >/dev/null || fail "Prime Agent npm values do not consume pin key $key"
  done < <(jq -r '.npm | keys[]' "$prime")
}

sorted_workflow_paths() {
  local workflow=$1 query=$2
  yq -r "$query" "$workflow" | LC_ALL=C sort
}

validate_workflows() {
  local root=$1
  local fix=$root/$FIX_WORKFLOW_REL check=$root/$CHECK_WORKFLOW_REL
  local expected_paths actual condition run base_ref

  actionlint "$fix" "$check"

  expected_paths=$(printf '%s\n' "$OMP_PIN_REL" "$PI_PIN_REL" "$PRIME_PIN_REL" | LC_ALL=C sort)
  actual=$(sorted_workflow_paths "$fix" '.on.pull_request.paths[]')
  [ "$actual" = "$expected_paths" ] || fail "fix workflow paths do not match the three pin manifests"
  [ "$(yq -r '.on.pull_request.branches[]' "$fix")" = main ] \
    || fail "fix workflow must target main"
  condition=$(yq -r '.jobs.fix-hashes.if' "$fix")
  [ "$condition" = "startsWith(github.head_ref, 'renovate/')" ] \
    || fail "fix workflow Renovate branch guard changed"

  [ "$(yq -r '.jobs.fix-hashes.steps[] | select(.uses == "actions/checkout@v7") | .with.ref' "$fix")" = '${{ github.head_ref }}' ] \
    || fail "fix workflow checkout must use the PR head"
  [ "$(yq -r '.jobs.fix-hashes.steps[] | select(.uses == "actions/checkout@v7") | .with.fetch-depth' "$fix")" = 0 ] \
    || fail "fix workflow checkout must fetch history"
  [ "$(yq -r '.jobs.fix-hashes.steps[] | select(.uses == "nixbuild/nix-quick-install-action@v35") | .uses' "$fix")" = nixbuild/nix-quick-install-action@v35 ] \
    || fail "fix workflow must install Nix"
  [ "$(yq -r '.jobs.fix-hashes.steps[] | select(.uses == "actions/setup-node@v7") | .with.node-version' "$fix")" = 24 ] \
    || fail "fix workflow must install Node.js 24"

  run=$(yq -r '.jobs.fix-hashes.steps[] | select(.name == "Fix Nix hashes") | .run' "$fix")
  base_ref=$(yq -r '.jobs.fix-hashes.steps[] | select(.name == "Fix Nix hashes") | .env.BASE_REF' "$fix")
  [ "$run" = 'bash scripts/fix-nix-hashes.sh update "origin/$BASE_REF"' ] \
    || fail "fix workflow must invoke the shared updater exactly once"
  [ "$base_ref" = '${{ github.base_ref }}' ] || fail "fix workflow base ref changed"

  expected_paths=$(printf '%s\n' \
    flake.nix flake.lock 'home-manager/**' 'checks/**' constants.nix \
    'patches/**' statix.toml "$CHECK_WORKFLOW_REL" "$FIX_WORKFLOW_REL" renovate.json "$SCRIPT_REL" \
    | LC_ALL=C sort)
  for query in '.on.push.paths[]' '.on.pull_request.paths[]'; do
    actual=$(sorted_workflow_paths "$check" "$query")
    [ "$actual" = "$expected_paths" ] || fail "check workflow $query paths differ from its contract"
  done
}

validate_renovate() {
  local root=$1 manager_count tmp logs
  local config=$root/renovate.json

  renovate-config-validator --strict "$config" >/dev/null
  jq -e '
    (keys == ["$schema", "customManagers", "extends", "lockFileMaintenance", "nix"])
    and .extends == [
      "config:recommended",
      "abandonments:recommended",
      ":configMigration",
      "group:allNonMajor",
      "schedule:daily"
    ]
    and .nix == {"enabled": true}
  ' "$config" >/dev/null || fail "Renovate top-level contract changed"
  manager_count=$(jq --arg files "$PIN_MANAGER_PATTERN" --arg match "$PIN_MANAGER_MATCH" \
    --arg versioning "$VERSIONING_TEMPLATE" '[.customManagers[]? | select(
      (keys == ["customType", "managerFilePatterns", "matchStrings", "versioningTemplate"])
      and
      .customType == "regex"
      and .managerFilePatterns == [$files]
      and .matchStrings == [$match]
      and .versioningTemplate == $versioning
    )] | length' "$config")
  [ "$manager_count" -eq 1 ] || fail "expected one complete pin custom manager"

  tmp=$(mktemp -d)
  mkdir -p "$tmp/$PIN_DIR_REL"
  cp "$root/$PI_PIN_REL" "$tmp/$PI_PIN_REL"
  cp "$root/$OMP_PIN_REL" "$tmp/$OMP_PIN_REL"
  cp "$root/$PRIME_PIN_REL" "$tmp/$PRIME_PIN_REL"
  cp "$config" "$tmp/renovate.json"
  logs=$tmp/renovate.log
  (
    cd "$tmp"
    LOG_LEVEL=debug LOG_FORMAT=json renovate --platform=local --dry-run=extract > "$logs"
  )
  jq -s -e \
    --arg ompVersion "$(jq -r .version "$root/$OMP_PIN_REL")" \
    --arg piVersion "$(jq -r .version "$root/$PI_PIN_REL")" \
    --arg primeVersion "$(jq -r .version "$root/$PRIME_PIN_REL")" '
      [
        .[]
        | select(.msg == "Extracted dependencies")
        | .packageFiles.regex[]?
        | . as $file
        | .deps[]?
        | {
            packageFile: $file.packageFile,
            datasource,
            depName,
            currentValue,
            versioning
          }
      ]
      | sort_by(.packageFile)
      == [
        {
          packageFile: "home-manager/modules/development/pins/omp.json",
          datasource: "github-releases",
          depName: "can1357/oh-my-pi",
          currentValue: $ompVersion,
          versioning: "semver"
        },
        {
          packageFile: "home-manager/modules/development/pins/pi.json",
          datasource: "npm",
          depName: "@earendil-works/pi-coding-agent",
          currentValue: $piVersion,
          versioning: "semver"
        },
        {
          packageFile: "home-manager/modules/development/pins/prime-agent.json",
          datasource: "github-releases",
          depName: "PrimeIntellect-ai/prime-agent",
          currentValue: $primeVersion,
          versioning: "semver"
        }
      ]
    ' "$logs" >/dev/null || fail "Renovate pin extraction differs from the effective contract"
  rm -rf "$tmp"
}

validate_contract() {
  local root=$1 effective=$2
  require_command actionlint
  require_command jq
  require_command renovate
  require_command renovate-config-validator
  require_command yq
  validate_pin_files "$root/$PI_PIN_REL" "$root/$OMP_PIN_REL" "$root/$PRIME_PIN_REL"
  validate_effective_contract "$root" "$effective"
  validate_workflows "$root"
  validate_renovate "$root"
}

set_json() {
  local file=$1
  shift
  local output
  output=$(mktemp)
  jq "$@" "$file" > "$output"
  mv "$output" "$file"
}

path_changed_from_base() {
  local base=$1 path=$2 status

  if git diff --quiet "$base" -- "$path"; then
    return 1
  else
    status=$?
  fi
  [ "$status" -eq 1 ] || fail "cannot compare $path against base ref $base"
}

update_pi() {
  local root=$1 pin=$2 lock_output=$3
  local version template url fetch_hash workdir npm_hash
  version=$(jq -r .version "$pin")
  template=$(jq -r .src.urlTemplate "$pin")
  url=$(render_url "$template" "$version")
  fetch_hash=$(nix store prefetch-file --unpack --json "$url" | jq -r .hash)
  [[ $fetch_hash == sha256-* ]] || fail "invalid Pi source hash: $fetch_hash"

  workdir=$(mktemp -d)
  curl -sfSL "$url" | tar xz -C "$workdir" --strip-components=1
  (
    cd "$workdir"
    rm -f npm-shrinkwrap.json
    npm install --package-lock-only --ignore-scripts --no-audit --no-fund
    npm_hash=$(nix run nixpkgs#prefetch-npm-deps -- ./package-lock.json)
    [[ $npm_hash == sha256-* ]] || fail "invalid Pi npm hash: $npm_hash"
    cp package-lock.json "$lock_output"
    set_json "$pin" --arg src "$fetch_hash" --arg npm "$npm_hash" \
      '.src.hash = $src | .npmDepsHash = $npm'
  )
  rm -rf "$workdir"
}

update_omp() {
  local pin=$1 version template key url hash
  version=$(jq -r .version "$pin")
  template=$(jq -r .urlTemplate "$pin")
  while IFS= read -r key; do
    url=$(render_url "$template" "$version" "$key")
    hash=$(nix store prefetch-file --json "$url" | jq -r .hash)
    [[ $hash == sha256-* ]] || fail "invalid OMP hash for $key: $hash"
    set_json "$pin" --arg key "$key" --arg hash "$hash" '.hashes[$key] = $hash'
  done < <(jq -r '.hashes | keys[]' "$pin")
}

update_prime_agent() {
  local pin=$1 version template url hash lock key new_version dependency_url dependency_hash
  local bootstrap upstream expected snapshot
  version=$(jq -r .version "$pin")
  template=$(jq -r .src.urlTemplate "$pin")
  url=$(render_url "$template" "$version")
  hash=$(nix store prefetch-file --unpack --json "$url" | jq -r .hash)
  [[ $hash == sha256-* ]] || fail "invalid Prime Agent source hash: $hash"
  set_json "$pin" --arg hash "$hash" '.src.hash = $hash'

  lock=$(mktemp)
  curl -sfSL "https://raw.githubusercontent.com/PrimeIntellect-ai/prime-agent/v${version}/package-lock.json" -o "$lock" \
    || fail "upstream package-lock.json missing for Prime Agent $version"
  while IFS= read -r key; do
    new_version=$(jq -r --arg key "node_modules/$key" '.packages[$key].version // empty' "$lock")
    [ -n "$new_version" ] || fail "$key absent from Prime Agent $version lock"
    template=$(jq -r --arg key "$key" '.npm[$key].urlTemplate' "$pin")
    dependency_url=$(render_url "$template" "$new_version")
    dependency_hash=$(nix store prefetch-file --unpack --json "$dependency_url" | jq -r .hash)
    [[ $dependency_hash == sha256-* ]] || fail "invalid hash for $key@$new_version"
    set_json "$pin" --arg key "$key" --arg version "$new_version" --arg hash "$dependency_hash" \
      '.npm[$key].version = $version | .npm[$key].hash = $hash'
  done < <(jq -r '.npm | keys[]' "$pin")
  rm -f "$lock"

  bootstrap=$(curl -sfSL "https://raw.githubusercontent.com/PrimeIntellect-ai/prime-agent/v${version}/packages/coding-agent/src/core/kernel/bootstrap.ts") \
    || fail "cannot fetch Prime Agent bootstrap.ts for $version"
  upstream=$(printf '%s\n' "$bootstrap" | grep -oE 'uvArg:[[:space:]]*"[^"]+"' \
    | sed -E 's/.*"([^"]+)".*/\1/' | LC_ALL=C sort -u | paste -sd' ' -)
  expected=$(jq -r '.rlmExtraPackages[]' "$pin" | paste -sd' ' -)
  [ -n "$upstream" ] && [ "$upstream" = "$expected" ] \
    || fail "Prime Agent RLM package drift: upstream=[$upstream] pinned=[$expected]"
  snapshot=$(printf '%s\n' "$bootstrap" \
    | grep -oE 'STATE_SNAPSHOT_REQUIREMENT[[:space:]]*=[[:space:]]*"[^"]+"' \
    | sed -E 's/.*"([^"]+)".*/\1/')
  [ "$snapshot" = "$(jq -r .snapshotRequirement "$pin")" ] \
    || fail "Prime Agent snapshot requirement drift: upstream=$snapshot"
}

update_contract() {
  local base=$1 root work pi_changed=false omp_changed=false prime_changed=false
  root=$(git rev-parse --show-toplevel)
  cd "$root"
  require_command jq
  git rev-parse --verify --quiet "${base}^{commit}" >/dev/null \
    || fail "base ref does not resolve to a commit: $base"
  validate_pin_files "$PI_PIN_REL" "$OMP_PIN_REL" "$PRIME_PIN_REL"

  if path_changed_from_base "$base" "$PI_PIN_REL"; then
    pi_changed=true
  fi
  if path_changed_from_base "$base" "$OMP_PIN_REL"; then
    omp_changed=true
  fi
  if path_changed_from_base "$base" "$PRIME_PIN_REL"; then
    prime_changed=true
  fi
  if ! $pi_changed && ! $omp_changed && ! $prime_changed; then
    echo "No dependency pin changes detected"
    return
  fi

  work=$(mktemp -d)
  cp "$PI_PIN_REL" "$work/pi.json"
  cp "$OMP_PIN_REL" "$work/omp.json"
  cp "$PRIME_PIN_REL" "$work/prime-agent.json"
  if $pi_changed; then
    update_pi "$root" "$work/pi.json" "$work/pi-package-lock.json"
  fi
  $omp_changed && update_omp "$work/omp.json"
  $prime_changed && update_prime_agent "$work/prime-agent.json"
  validate_pin_files "$work/pi.json" "$work/omp.json" "$work/prime-agent.json"

  $pi_changed && cp "$work/pi.json" "$PI_PIN_REL"
  if $pi_changed; then
    cp "$work/pi-package-lock.json" "$PI_LOCK_REL"
  fi
  $omp_changed && cp "$work/omp.json" "$OMP_PIN_REL"
  $prime_changed && cp "$work/prime-agent.json" "$PRIME_PIN_REL"
  rm -rf "$work"

  git config user.name "github-actions[bot]"
  git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
  git add "$PI_PIN_REL" "$OMP_PIN_REL" "$PRIME_PIN_REL" "$PI_LOCK_REL"
  if ! git diff --cached --quiet; then
    git commit -m "fix: update nix hashes for version bump"
    git push
  fi
}

case ${1:-} in
  validate)
    [ "$#" -eq 3 ] || fail "usage: $0 validate <root> <effective-contract.json>"
    validate_contract "$2" "$3"
    ;;
  update)
    [ "$#" -eq 2 ] || fail "usage: $0 update <base-ref>"
    update_contract "$2"
    ;;
  *)
    fail "usage: $0 {validate <root> <effective-contract.json>|update <base-ref>}"
    ;;
esac
