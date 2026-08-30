#!/usr/bin/env bash
set -euo pipefail

PIN_DIR_REL=home-manager/modules/development/pins
PI_PIN_REL=$PIN_DIR_REL/pi.json
OMP_PIN_REL=$PIN_DIR_REL/omp.json
PRIME_PIN_REL=$PIN_DIR_REL/prime-agent.json
PI_LOCK_REL=home-manager/modules/development/pi-package-lock.json
OPENSPEC_MODULE_REL=home-manager/modules/development/openspec.nix
FLAKE_LOCK_REL=flake.lock
FIX_WORKFLOW_REL=.github/workflows/fix-nix-hashes.yml
CHECK_WORKFLOW_REL=.github/workflows/check.yml
SCRIPT_REL=scripts/fix-nix-hashes.sh
OPENSPEC_INPUT=openspec
OPENSPEC_INSTALLABLE=.#homeConfigurations.almalinux.config.modules.development.openspec.package

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
    and (keys == ["npm", "python", "renovate", "rlmExtraPackages", "snapshotRequirement", "src", "version"])
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
    and (.python | keys == ["httpcore2", "httpx2", "mcp", "mcp-types"])
    and ([.python[] | keys == ["hash", "url", "version"]] | all)
    and ([.python[].hash | test($hash)] | all)
    and ([.python[].url | test("^https://files\\.pythonhosted\\.org/.+\\.whl$")] | all)
    and ([.python[].version | type == "string" and length > 0] | all)
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

  while IFS= read -r key; do
    jq -e --arg key "$key" --slurpfile pin "$prime" '
      .primeAgent.python[$key].version == $pin[0].python[$key].version
      and .primeAgent.python[$key].src.url == $pin[0].python[$key].url
      and .primeAgent.python[$key].src.hash == $pin[0].python[$key].hash
    ' "$effective" >/dev/null || fail "Prime Agent Python values do not consume pin key $key"
  done < <(jq -r '.python | keys[]' "$prime")
}

sorted_workflow_paths() {
  local workflow=$1 query=$2
  yq -r "$query" "$workflow" | LC_ALL=C sort
}

validate_action_ref() {
  local ref=$1 action=$2 digest
  digest=${ref#"$action@"}
  [ "$digest" != "$ref" ] && [[ $digest =~ ^[0-9a-f]{40}$ ]] \
    || fail "$action must be pinned to a full commit SHA"
}

validate_workflows() {
  local root=$1
  local fix=$root/$FIX_WORKFLOW_REL check=$root/$CHECK_WORKFLOW_REL
  local expected_paths actual condition run base_ref push_run
  local fix_checkout fix_nix fix_node check_checkout check_disk check_nix check_cache

  actionlint "$fix" "$check"

  [ "$(yq -r '[.jobs.fix-hashes.steps[] | select(has("uses"))] | length' "$fix")" -eq 3 ] \
    || fail "fix workflow must use exactly three actions"
  fix_checkout=$(yq -r '.jobs.fix-hashes.steps[] | select(.uses | test("^actions/checkout@")) | .uses' "$fix")
  fix_nix=$(yq -r '.jobs.fix-hashes.steps[] | select(.uses | test("^nixbuild/nix-quick-install-action@")) | .uses' "$fix")
  fix_node=$(yq -r '.jobs.fix-hashes.steps[] | select(.uses | test("^actions/setup-node@")) | .uses' "$fix")
  validate_action_ref "$fix_checkout" actions/checkout
  validate_action_ref "$fix_nix" nixbuild/nix-quick-install-action
  validate_action_ref "$fix_node" actions/setup-node

  expected_paths=$(printf '%s\n' "$FLAKE_LOCK_REL" "$OMP_PIN_REL" "$PI_PIN_REL" "$PRIME_PIN_REL" | LC_ALL=C sort)
  actual=$(sorted_workflow_paths "$fix" '.on.pull_request.paths[]')
  [ "$actual" = "$expected_paths" ] || fail "fix workflow paths do not match dependency inputs"
  [ "$(yq -r '.on.pull_request.branches[]' "$fix")" = main ] \
    || fail "fix workflow must target main"
  condition=$(yq -r '.jobs.fix-hashes.if' "$fix")
  [ "$condition" = "startsWith(github.head_ref, 'renovate/')" ] \
    || fail "fix workflow Renovate branch guard changed"

  [ "$(yq -r '.jobs.fix-hashes.steps[] | select(.uses | test("^actions/checkout@")) | .with.ref' "$fix")" = '${{ github.head_ref }}' ] \
    || fail "fix workflow checkout must use the PR head"
  [ "$(yq -r '.jobs.fix-hashes.steps[] | select(.uses | test("^actions/checkout@")) | .with.fetch-depth' "$fix")" = 0 ] \
    || fail "fix workflow checkout must fetch history"
  [ "$(yq -r '.jobs.fix-hashes.steps[] | select(.uses | test("^actions/checkout@")) | .with.persist-credentials' "$fix")" = false ] \
    || fail "fix workflow checkout must not persist credentials"
  [ "$(yq -r '.jobs.fix-hashes.steps[] | select(.uses | test("^actions/checkout@")) | .with.token // ""' "$fix")" = "" ] \
    || fail "fix workflow checkout must not receive an explicit token"
  [ -n "$fix_nix" ] || fail "fix workflow must install Nix"
  [ "$(yq -r '.jobs.fix-hashes.steps[] | select(.uses | test("^nixbuild/nix-quick-install-action@")) | .with.github_access_token' "$fix")" = "" ] \
    || fail "fix workflow Nix installer must not persist the GitHub token"
  [ "$(yq -r '.jobs.fix-hashes.steps[] | select(.uses | test("^actions/setup-node@")) | .with.node-version' "$fix")" = 24 ] \
    || fail "fix workflow must install Node.js 24"

  run=$(yq -r '.jobs.fix-hashes.steps[] | select(.name == "Fix Nix hashes") | .run' "$fix")
  base_ref=$(yq -r '.jobs.fix-hashes.steps[] | select(.name == "Fix Nix hashes") | .env.BASE_REF' "$fix")
  [ "$run" = 'bash scripts/fix-nix-hashes.sh update "origin/$BASE_REF"' ] \
    || fail "fix workflow must invoke the shared updater exactly once"
  [ "$base_ref" = '${{ github.base_ref }}' ] || fail "fix workflow base ref changed"
  actual=$(yq -r '.jobs.fix-hashes.steps[] | select(.name == "Fix Nix hashes") | .env | keys | .[]' "$fix")
  [ "$actual" = BASE_REF ] || fail "fix workflow updater must not receive push credentials"

  push_run=$(yq -r '.jobs.fix-hashes.steps[] | select(.name == "Push Nix hash fix") | .run' "$fix")
  [ "$push_run" = 'bash scripts/fix-nix-hashes.sh push "$GITHUB_REPOSITORY" "$HEAD_REF"' ] \
    || fail "fix workflow must isolate the authenticated push"
  [ "$(yq -r '.jobs.fix-hashes.steps[] | select(.name == "Push Nix hash fix") | .env.PUSH_TOKEN' "$fix")" = '${{ github.token }}' ] \
    || fail "fix workflow push token changed"
  [ "$(yq -r '.jobs.fix-hashes.steps[] | select(.name == "Push Nix hash fix") | .env.GITHUB_REPOSITORY' "$fix")" = '${{ github.repository }}' ] \
    || fail "fix workflow push repository changed"
  [ "$(yq -r '.jobs.fix-hashes.steps[] | select(.name == "Push Nix hash fix") | .env.HEAD_REF' "$fix")" = '${{ github.head_ref }}' ] \
    || fail "fix workflow push branch changed"
  expected_paths=$(printf '%s\n' GITHUB_REPOSITORY HEAD_REF PUSH_TOKEN | LC_ALL=C sort)
  actual=$(yq -r '.jobs.fix-hashes.steps[] | select(.name == "Push Nix hash fix") | .env | keys | .[]' "$fix" | LC_ALL=C sort)
  [ "$actual" = "$expected_paths" ] || fail "fix workflow push environment differs from its contract"

  expected_paths=$(printf '%s\n' \
    flake.nix flake.lock 'home-manager/**' 'checks/**' constants.nix \
    'patches/**' statix.toml Makefile 'scripts/**' 'secrets/**' .sops.yaml .gitignore \
    "$CHECK_WORKFLOW_REL" "$FIX_WORKFLOW_REL" renovate.json "$SCRIPT_REL" \
    | LC_ALL=C sort)
  for query in '.on.push.paths[]' '.on.pull_request.paths[]'; do
    actual=$(sorted_workflow_paths "$check" "$query")
    [ "$actual" = "$expected_paths" ] || fail "check workflow $query paths differ from its contract"
  done

  [ "$(yq -r '[.jobs.check.steps[] | select(has("uses"))] | length' "$check")" -eq 4 ] \
    || fail "check workflow must use exactly four actions"
  check_checkout=$(yq -r '.jobs.check.steps[] | select(.uses | test("^actions/checkout@")) | .uses' "$check")
  check_disk=$(yq -r '.jobs.check.steps[] | select(.uses | test("^wimpysworld/nothing-but-nix@")) | .uses' "$check")
  check_nix=$(yq -r '.jobs.check.steps[] | select(.uses | test("^nixbuild/nix-quick-install-action@")) | .uses' "$check")
  check_cache=$(yq -r '.jobs.check.steps[] | select(.uses | test("^nix-community/cache-nix-action@")) | .uses' "$check")
  validate_action_ref "$check_checkout" actions/checkout
  validate_action_ref "$check_disk" wimpysworld/nothing-but-nix
  validate_action_ref "$check_nix" nixbuild/nix-quick-install-action
  validate_action_ref "$check_cache" nix-community/cache-nix-action
  [ "$(yq -r '.jobs.check.steps[] | select(.uses | test("^nixbuild/nix-quick-install-action@")) | .with.github_access_token' "$check")" = "" ] \
    || fail "check workflow Nix installer must not persist the GitHub token"
  [ "$(yq -r '.jobs.check.steps[] | select(.uses | test("^actions/checkout@")) | .with.persist-credentials' "$check")" = false ] \
    || fail "check workflow checkout must not persist credentials"
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
  validate_openspec_module "$root/$OPENSPEC_MODULE_REL"
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

path_changed_since() {
  local commit=$1 path=$2 status

  if git diff --quiet "$commit" HEAD -- "$path"; then
    return 1
  else
    status=$?
  fi
  [ "$status" -eq 1 ] || fail "cannot compare $path between $commit and HEAD"
}
lock_input_fingerprint() {
  local input=$1
  jq -c --arg input "$input" '
    .nodes as $nodes
    | (.nodes.root.inputs[$input] // null) as $node
    | if ($node | type) == "string" then ($nodes[$node].locked // null) else null end
  '
}

flake_input_changed_since() {
  local commit=$1 input=$2 before after
  before=$(git show "$commit:$FLAKE_LOCK_REL" | lock_input_fingerprint "$input") \
    || fail "cannot read $input from $FLAKE_LOCK_REL at $commit"
  after=$(lock_input_fingerprint "$input" < "$FLAKE_LOCK_REL") \
    || fail "cannot read $input from $FLAKE_LOCK_REL at HEAD"
  [ "$before" != "$after" ]
}

validate_openspec_module() {
  local module=$1
  [ "$(grep -Ec '^  pnpmDepsHash = "sha256-[A-Za-z0-9+/=]+";$' "$module")" -eq 1 ] \
    || fail "OpenSpec module must contain exactly one literal pnpmDepsHash"
}

set_openspec_hash() {
  local module=$1 hash=$2 output
  [[ $hash =~ $HASH_PATTERN ]] || fail "invalid OpenSpec pnpm hash: $hash"
  validate_openspec_module "$module"
  output=$(mktemp)
  sed -E 's|^  pnpmDepsHash = "sha256-[A-Za-z0-9+/=]+";|  pnpmDepsHash = "'"$hash"'";|' \
    "$module" > "$output"
  grep -Fqx '  pnpmDepsHash = "'"$hash"'";' "$output" \
    || fail "cannot update OpenSpec pnpm hash"
  mv "$output" "$module"
}

update_openspec() {
  local module=$1 backup output hash matches
  if output=$(nix build --no-link "$OPENSPEC_INSTALLABLE" 2>&1); then
    echo "OpenSpec pnpm hash is current"
    return
  fi

  matches=$(printf '%s\n' "$output" \
    | sed -nE 's/^[[:space:]]*got:[[:space:]]*(sha256-[A-Za-z0-9+\/=]+)[[:space:]]*$/\1/p' \
    | LC_ALL=C sort -u)
  if [ "$(printf '%s\n' "$matches" | sed '/^$/d' | wc -l)" -ne 1 ]; then
    printf '%s\n' "$output" >&2
    fail "OpenSpec build did not report exactly one dependency hash"
  fi
  hash=$matches
  [[ $hash =~ $HASH_PATTERN ]] || {
    printf '%s\n' "$output" >&2
    fail "OpenSpec build reported an invalid dependency hash"
  }

  backup=$(mktemp)
  cp "$module" "$backup"
  trap 'cp "$backup" "$module"; rm -f "$backup"' EXIT
  set_openspec_hash "$module" "$hash"
  if ! output=$(nix build --no-link "$OPENSPEC_INSTALLABLE" 2>&1); then
    printf '%s\n' "$output" >&2
    fail "OpenSpec package does not build with the refreshed dependency hash"
  fi

  trap - EXIT
  rm -f "$backup"
  printf 'Updated OpenSpec pnpm hash to %s\n' "$hash"
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
    npm_hash=$(nix run --inputs-from "$root" nixpkgs#prefetch-npm-deps -- ./package-lock.json)
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
  local archive runtime_dir runtime_lock runtime_json wheel wheel_hash
  local bootstrap upstream expected snapshot
  version=$(jq -r .version "$pin")
  template=$(jq -r .src.urlTemplate "$pin")
  url=$(render_url "$template" "$version")
  archive=$(mktemp)
  curl -sfSL "$url" -o "$archive" || fail "cannot download Prime Agent $version release"
  hash=$(nix store prefetch-file --unpack --json "file://$archive" | jq -r .hash)
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

  runtime_dir=$(mktemp -d)
  tar -xzf "$archive" -C "$runtime_dir"
  runtime_lock=$runtime_dir/package/dist/prime-agent-runtime/uv.lock
  [ -f "$runtime_lock" ] || fail "Prime Agent $version runtime uv.lock missing"
  [ -f "$runtime_dir/package/dist/prime-agent-runtime/pyproject.toml" ] \
    || fail "Prime Agent $version runtime pyproject.toml missing"
  runtime_json=$(nix eval --impure --json --expr "builtins.fromTOML (builtins.readFile $runtime_lock)")
  while IFS= read -r key; do
    new_version=$(jq -r --arg key "$key" '
      [.package[] | select(.name == $key)] | if length == 1 then .[0].version else empty end
    ' <<<"$runtime_json")
    wheel=$(jq -r --arg key "$key" '
      [.package[] | select(.name == $key)][0].wheels
      | map(select(.url | endswith("-py3-none-any.whl")))
      | if length == 1 then .[0] else empty end
    ' <<<"$runtime_json")
    [ -n "$new_version" ] && [ -n "$wheel" ] \
      || fail "$key has no unique py3-none-any wheel in Prime Agent $version runtime lock"
    dependency_url=$(jq -r .url <<<"$wheel")
    wheel_hash=$(jq -r .hash <<<"$wheel")
    [[ $wheel_hash == sha256:* ]] || fail "invalid uv hash for $key@$new_version"
    dependency_hash=$(nix hash convert --hash-algo sha256 --to sri "${wheel_hash#sha256:}")
    set_json "$pin" \
      --arg key "$key" \
      --arg version "$new_version" \
      --arg url "$dependency_url" \
      --arg hash "$dependency_hash" \
      '.python[$key].version = $version | .python[$key].url = $url | .python[$key].hash = $hash'
  done < <(jq -r '.python | keys[]' "$pin")
  rm -f "$archive"
  rm -rf "$runtime_dir"

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
  local base=$1 root work merge_base
  local pi_changed=false omp_changed=false prime_changed=false openspec_changed=false
  root=$(git rev-parse --show-toplevel)
  cd "$root"
  require_command jq
  git rev-parse --verify --quiet "${base}^{commit}" >/dev/null \
    || fail "base ref does not resolve to a commit: $base"
  merge_base=$(git merge-base "$base" HEAD) \
    || fail "cannot determine merge base between $base and HEAD"
  validate_pin_files "$PI_PIN_REL" "$OMP_PIN_REL" "$PRIME_PIN_REL"
  validate_openspec_module "$OPENSPEC_MODULE_REL"

  if path_changed_since "$merge_base" "$PI_PIN_REL"; then
    pi_changed=true
  fi
  if path_changed_since "$merge_base" "$OMP_PIN_REL"; then
    omp_changed=true
  fi
  if path_changed_since "$merge_base" "$PRIME_PIN_REL"; then
    prime_changed=true
  fi
  if path_changed_since "$merge_base" "$FLAKE_LOCK_REL" \
    && flake_input_changed_since "$merge_base" "$OPENSPEC_INPUT"; then
    openspec_changed=true
  fi
  if ! $pi_changed && ! $omp_changed && ! $prime_changed && ! $openspec_changed; then
    echo "No supported dependency changes detected"
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
  $openspec_changed && update_openspec "$OPENSPEC_MODULE_REL"

  $pi_changed && cp "$work/pi.json" "$PI_PIN_REL"
  if $pi_changed; then
    cp "$work/pi-package-lock.json" "$PI_LOCK_REL"
  fi
  $omp_changed && cp "$work/omp.json" "$OMP_PIN_REL"
  $prime_changed && cp "$work/prime-agent.json" "$PRIME_PIN_REL"
  rm -rf "$work"

  git config user.name "github-actions[bot]"
  git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
  git add "$PI_PIN_REL" "$OMP_PIN_REL" "$PRIME_PIN_REL" "$PI_LOCK_REL" "$OPENSPEC_MODULE_REL"
  if ! git diff --cached --quiet; then
    git commit -m "fix: update nix hashes for version bump"
  fi
}

push_hash_fix() {
  local repository=$1 head_ref=$2 askpass status
  [ -n "${PUSH_TOKEN:-}" ] || fail "PUSH_TOKEN is required"
  [[ $repository =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] \
    || fail "invalid GitHub repository: $repository"
  git check-ref-format --branch "$head_ref" >/dev/null 2>&1 \
    || fail "invalid GitHub head ref: $head_ref"

  umask 077
  askpass=$(mktemp)
  cat > "$askpass" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
case ${1:-} in
  Password*) printf '%s\n' "$PUSH_TOKEN" ;;
  *) exit 1 ;;
esac
EOF
  chmod 700 "$askpass"
  if GIT_ASKPASS="$askpass" GIT_TERMINAL_PROMPT=0 \
    git -c credential.helper= -c core.hooksPath=/dev/null push \
      "https://x-access-token@github.com/${repository}.git" \
      "HEAD:refs/heads/${head_ref}"; then
    rm -f "$askpass"
  else
    status=$?
    rm -f "$askpass"
    return "$status"
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
  push)
    [ "$#" -eq 3 ] || fail "usage: $0 push <repository> <head-ref>"
    require_command git
    push_hash_fix "$2" "$3"
    ;;
  *)
    fail "usage: $0 {validate <root> <effective-contract.json>|update <base-ref>|push <repository> <head-ref>}"
    ;;
esac
