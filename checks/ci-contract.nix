{
  self,
  pkgs,
  nixpkgs,
  home-manager,
}:

let
  lib = pkgs.lib;
  sources = import ../home-manager/modules/development/pins {
    inherit (pkgs) lib;
    fetchurl = arguments: arguments;
    fetchzip = arguments: arguments;
  };
  primeAgentSource = pkgs.fetchzip sources.primeAgent.src;
  primeAgentRuntimeRoot = "${primeAgentSource}/prime-agent-runtime";
  primeAgentRuntimeProject = lib.importTOML "${primeAgentRuntimeRoot}/pyproject.toml";
  primeAgentRuntimeLock = lib.importTOML "${primeAgentRuntimeRoot}/uv.lock";
  dummyPythonPackages = lib.genAttrs [
    "beautifulsoup4"
    "httpx"
    "lxml"
    "numpy"
    "pandas"
    "pydantic"
    "python-dotenv"
    "pyyaml"
    "requests"
    "tomli"
  ] (name: name);
  rlmPackages = import ../home-manager/modules/development/pins/rlm-packages.nix {
    ps = dummyPythonPackages;
    scipy = "scipy";
    tyro = "tyro";
  };

  platformKeys = {
    aarch64-darwin = "darwin-arm64";
    aarch64-linux = "linux-arm64";
    x86_64-linux = "linux-x64";
  };
  consumerSystems = builtins.attrNames platformKeys;
  mkConsumer =
    system: enabledModule:
    home-manager.lib.homeManagerConfiguration {
      pkgs = import nixpkgs { inherit system; };
      modules = [
        ../home-manager/modules/core/lib.nix
        ../home-manager/modules/development/pi.nix
        ../home-manager/modules/development/omp.nix
        ../home-manager/modules/development/prime-agent.nix
        {
          home = {
            username = "ci-contract";
            homeDirectory = if system == "aarch64-darwin" then "/Users/ci-contract" else "/home/ci-contract";
            stateVersion = "26.05";
          };
          modules.development.${enabledModule}.enable = true;
        }
      ];
    };
  consumerPackages = lib.genAttrs consumerSystems (
    system:
    let
      piConfig = (mkConsumer system "pi").config;
      ompConfig = (mkConsumer system "omp").config;
      primeAgentConfig = (mkConsumer system "primeAgent").config;
    in
    {
      pi = piConfig.modules.development.pi.package;
      omp = ompConfig.modules.development.omp.package;
      primeAgent = primeAgentConfig.modules.development.primeAgent.package;
      installed = {
        inherit (piConfig.home) packages;
        omp = ompConfig.home.packages;
        primeAgent = primeAgentConfig.home.packages;
      };
    }
  );

  consumerContractValid =
    system:
    let
      packages = consumerPackages.${system};
      piPackage = packages.pi;
      ompPackage = packages.omp;
      primeAgentPackage = packages.primeAgent;
      expectedKernelNames = lib.sort builtins.lessThan (
        [
          "rlm"
          sources.primeAgent.snapshotRequirement
        ]
        ++ sources.primeAgent.rlmExtraPackages
      );
      pythonRuntimePackages = primeAgentPackage.pythonRuntimePackages;
      runtimeProject = primeAgentRuntimeProject;
      runtimeLock = primeAgentRuntimeLock;
      dependencyName =
        requirement:
        let
          matched = builtins.match "([A-Za-z0-9_.-]+).*" requirement;
        in
        builtins.elemAt matched 0;
      declaredRuntimeDependencies = lib.sort builtins.lessThan (
        map dependencyName runtimeProject.project.dependencies
      );
      expectedRlm = primeAgentPackage.runtimePackage;
      actualRuntimeDependencies = lib.sort builtins.lessThan (
        map (dependency: dependency.pname) expectedRlm.dependencies
      );
      pythonRuntimePackageValid =
        name:
        let
          actual = pythonRuntimePackages.${name};
          expected = sources.primeAgent.python.${name};
          locked = lib.findFirst (package: package.name == name) null runtimeLock.package;
          lockedWheels =
            if locked == null then
              [ ]
            else
              builtins.filter (wheel: lib.hasSuffix "-py3-none-any.whl" wheel.url) locked.wheels;
          lockedWheel = if builtins.length lockedWheels == 1 then builtins.head lockedWheels else null;
          lockedWheelHash =
            if lockedWheel == null then
              null
            else
              builtins.convertHash {
                hash = lib.removePrefix "sha256:" lockedWheel.hash;
                hashAlgo = "sha256";
                toHashFormat = "sri";
              };
        in
        locked != null
        && lockedWheel != null
        && actual.version == locked.version
        && actual.version == expected.version
        && actual.src.url == lockedWheel.url
        && actual.src.url == expected.src.url
        && actual.src.outputHash == lockedWheelHash
        && actual.src.outputHash == expected.src.hash;
      message = detail: "ci-contract (${system}): ${detail}";
    in
    lib.assertMsg (piPackage.version == sources.pi.version) (
      message "pi.nix ignores the pinned version"
    )
    && lib.assertMsg (
      builtins.elem piPackage packages.installed.packages
      && builtins.elem ompPackage packages.installed.omp
      && builtins.elem primeAgentPackage packages.installed.primeAgent
    ) (message "an enabled development module does not install its configured package")
    && lib.assertMsg (
      builtins.hashFile "sha256" piPackage.contractLockFile
      == builtins.hashFile "sha256" sources.pi.lockFile
    ) (message "pi.nix does not consume the pinned lock")
    && lib.assertMsg (ompPackage.version == sources.omp.version) (
      message "omp.nix ignores the pinned version"
    )
    && lib.assertMsg (primeAgentPackage.version == sources.primeAgent.version) (
      message "prime-agent.nix ignores the pinned version"
    )
    && lib.assertMsg (
      builtins.attrNames pythonRuntimePackages == builtins.attrNames sources.primeAgent.python
      && builtins.all pythonRuntimePackageValid (builtins.attrNames pythonRuntimePackages)
      && runtimeProject.project.name == "prime-agent-runtime"
      && runtimeProject.project.version == expectedRlm.version
      && declaredRuntimeDependencies == actualRuntimeDependencies
      && builtins.elem pythonRuntimePackages.mcp expectedRlm.dependencies
      && lib.versionAtLeast pythonRuntimePackages.mcp.version "2"
      && lib.versionOlder pythonRuntimePackages.mcp.version "3"
    ) (message "prime-agent.nix runtime package differs from the release Python lock")
    && lib.assertMsg (builtins.attrNames primeAgentPackage.kernelRequirements == expectedKernelNames) (
      message "prime-agent.nix kernel requirements differ from the pinned package set"
    );

  effectiveContract = {
    pi = {
      inherit (sources.pi)
        version
        src
        npmDepsHash
        ;
      lockFile = sources.pi.lockFileName;
    };
    omp = {
      inherit (sources.omp) version sources;
    };
    primeAgent = {
      inherit (sources.primeAgent)
        version
        src
        cargoHash
        rlmExtraPackages
        snapshotRequirement
        ;
      bundledCatalogs = {
        inherit (sources.primeAgent.bundledCatalogs) url hash;
      };
      python = lib.mapAttrs (_key: dependency: {
        inherit (dependency) version src;
      }) sources.primeAgent.python;
    };
  };
  effectiveContractFile = pkgs.writeText "ci-effective-contract.json" (
    builtins.toJSON effectiveContract
  );
  updateTestRlmExtraPackages = [
    "beautifulsoup4"
    "httpx"
    "lxml"
    "numpy"
    "pandas"
    "pydantic"
    "python-dotenv"
    "pyyaml"
    "requests"
    "scipy"
    "tomli"
    "tyro"
  ];
  updateTestBootstrap = lib.concatMapStringsSep "\n" (
    dependency: ''("${dependency}", "${dependency}", "${dependency}"),''
  ) updateTestRlmExtraPackages;
  updateTestNix = pkgs.writeShellScriptBin "nix" ''
    invocation=" $* "
    if [ "$#" -eq 6 ] && [ "$1" = run ] \
      && [ "$2" = --inputs-from ] && [ "$3" = "$MOCK_FLAKE_ROOT" ] \
      && [ "$4" = "nixpkgs#prefetch-npm-deps" ] && [ "$5" = -- ] \
      && [ "$6" = ./package-lock.json ]; then
      hash=sha256-BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB=
    elif [ "$#" -eq 5 ] && [ "$1" = store ] && [ "$2" = prefetch-file ] \
      && [ "$3" = --unpack ] && [ "$4" = --json ]; then
      case "$5" in
        "https://registry.npmjs.org/@earendil-works/pi-coding-agent/-/pi-coding-agent-9.9.9.tgz")
          hash=sha256-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=
          ;;
        file://* | "https://github.com/PrimeIntellect-ai/prime-agent/archive/refs/tags/v9.9.9.tar.gz" | \
          "https://github.com/PrimeIntellect-ai/prime-agent/archive/refs/tags/v9.9.10.tar.gz")
          hash=sha256-PPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPP=
          ;;
        "https://github.com/PrimeIntellect-ai/prime-agent/releases/download/v9.9.9/prime-agent-9.9.9-linux-x64.tar.gz")
          hash=sha256-MMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM=
          ;;
        *)
          echo "unexpected unpacked prefetch URL:$5" >&2
          exit 1
          ;;
      esac
    elif [ "$#" -eq 4 ] && [ "$1" = store ] && [ "$2" = prefetch-file ] \
      && [ "$3" = --json ]; then
      case "$4" in
        "https://github.com/can1357/oh-my-pi/releases/download/v9.9.9/omp-darwin-arm64")
          hash=sha256-DDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDD=
          ;;
        "https://github.com/can1357/oh-my-pi/releases/download/v9.9.9/omp-linux-arm64")
          hash=sha256-LLLLLLLLLLLLLLLLLLLLLLLLLLLLLLLLLLLLLLLLLLL=
          ;;
        "https://github.com/can1357/oh-my-pi/releases/download/v9.9.9/omp-linux-x64")
          hash=sha256-XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX=
          ;;
        *)
          echo "unexpected flat prefetch URL:$4" >&2
          exit 1
          ;;
      esac
    elif [ "$#" -eq 5 ] && [ "$1" = build ] && [ "$2" = --impure ] \
      && [ "$3" = --no-link ] && [ "$4" = --expr ]; then
      if [ "$NIX_HASH_FIX_ROOT" != "$MOCK_FLAKE_ROOT" ] \
        || [ "$NIX_HASH_FIX_URL" != "https://github.com/PrimeIntellect-ai/prime-agent/archive/refs/tags/v9.9.9.tar.gz" ] \
        || [ "$NIX_HASH_FIX_SOURCE_HASH" != sha256-PPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPP= ]; then
        echo "unexpected Cargo vendoring source" >&2
        exit 1
      fi
      if [ -n "''${MOCK_CARGO_WRONG_MISMATCH:-}" ]; then
        cat >&2 <<'EOF'
    error: hash mismatch in fixed-output derivation '/nix/store/00000000000000000000000000000000-other-vendor-staging.drv':
             specified: sha256-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=
                got:    sha256-CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC=
    EOF
        exit 1
      fi
      cat >&2 <<'EOF'
    error: hash mismatch in fixed-output derivation '/nix/store/00000000000000000000000000000000-prime-agent-vendor-staging.drv':
             specified: sha256-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=
                got:    sha256-CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC=
    EOF
      exit 1
    elif [ "$#" -eq 5 ] && [ "$1" = eval ] && [ "$2" = --impure ] && [ "$3" = --json ] && [ "$4" = --expr ]; then
      exec ${pkgs.nix}/bin/nix --extra-experimental-features nix-command "$@"
    elif [ "$#" -eq 7 ] && [ "$1" = hash ] && [ "$2" = convert ] \
      && [ "$3" = --hash-algo ] && [ "$4" = sha256 ] \
      && [ "$5" = --to ] && [ "$6" = sri ]; then
      case "$7" in
        $(printf 'a%.0s' {1..64})) hash=sha256-1111111111111111111111111111111111111111111= ;;
        $(printf 'b%.0s' {1..64})) hash=sha256-2222222222222222222222222222222222222222222= ;;
        $(printf 'c%.0s' {1..64})) hash=sha256-3333333333333333333333333333333333333333333= ;;
        $(printf 'd%.0s' {1..64})) hash=sha256-4444444444444444444444444444444444444444444= ;;
        *)
          echo "unexpected hash conversion:$7" >&2
          exit 1
          ;;
      esac
      printf '%s\n' "$hash"
      exit
    else
      echo "unexpected nix invocation:$invocation" >&2
      exit 1
    fi
    if [ "$1" = run ]; then
      printf '%s\n' "$hash"
    else
      printf '{"hash":"%s"}\n' "$hash"
    fi
  '';
  updateTestCurl = pkgs.writeShellScriptBin "curl" ''
    set -euo pipefail
    if [ "$#" -eq 4 ] && [ "$1" = -sfSL ] && [ "$3" = -o ]; then
      case "$2" in
        "https://github.com/PrimeIntellect-ai/prime-agent/archive/refs/tags/v9.9.9.tar.gz" | \
          "https://github.com/PrimeIntellect-ai/prime-agent/archive/refs/tags/v9.9.10.tar.gz")
          source=$(mktemp -d)
          tar xzf "$MOCK_PRIME_TARBALL" -C "$source"
          bootstrap="$source/prime-agent-9.9.9/crates/pa-core/src/kernel/bootstrap"
          count=${toString (builtins.length updateTestRlmExtraPackages)}
          if [ -n "''${MOCK_RLM_DRIFT:-}" ]; then
            count=$((count + 1))
          fi
          {
            printf 'pub const DEFAULT_RLM_EXTRA_PACKAGES: [(&str, &str, &str); %s] = [\n' "$count"
            printf '%s\n' ${lib.escapeShellArg updateTestBootstrap}
            if [ -n "''${MOCK_RLM_DRIFT:-}" ]; then
              printf '%s\n' '("unpinned-package", "unpinned_package", "unpinned-package"),'
            fi
            printf '%s\n' '];'
          } > "$bootstrap/mod.rs"
          if [ -n "''${MOCK_SNAPSHOT_DRIFT:-}" ]; then
            snapshot=cloudpickle
          else
            snapshot=dill
          fi
          printf 'pub(super) const STATE_SNAPSHOT_REQUIREMENT: &str = "%s";\n' "$snapshot" \
            > "$bootstrap/venv/version.rs"
          tar czf "$4" -C "$source" prime-agent-9.9.9
          rm -rf "$source"
          ;;
        *)
          echo "unexpected archive URL:$2" >&2
          exit 1
          ;;
      esac
    elif [ "$#" -eq 2 ] && [ "$1" = -sfSL ] \
      && [ "$2" = "https://registry.npmjs.org/@earendil-works/pi-coding-agent/-/pi-coding-agent-9.9.9.tgz" ]; then
      cat "$MOCK_PI_TARBALL"
    else
      echo "unexpected curl invocation:$*" >&2
      exit 1
    fi
  '';
  updateTestNpm = pkgs.writeShellScriptBin "npm" ''
    set -euo pipefail
    if [ "$#" -ne 5 ] || [ "$1" != install ] || [ "$2" != --package-lock-only ] \
      || [ "$3" != --ignore-scripts ] || [ "$4" != --no-audit ] || [ "$5" != --no-fund ]; then
      echo "unexpected npm invocation: $*" >&2
      exit 1
    fi
    if [ ! -f package.json ]; then
      echo "npm fixture requires an extracted package.json" >&2
      exit 1
    fi
    name=$(jq -er '.name | select(type == "string" and length > 0)' package.json) \
      || {
        echo "npm fixture package.json requires a name" >&2
        exit 1
      }
    jq -n --arg name "$name" '{
      name: $name,
      lockfileVersion: 3,
      packages: {"": {name: $name}}
    }' > package-lock.json
  '';
in
assert
  consumerSystems == [
    "aarch64-darwin"
    "aarch64-linux"
    "x86_64-linux"
  ];
assert
  lib.sort builtins.lessThan (builtins.attrValues platformKeys)
  == builtins.attrNames sources.omp.sources;
assert builtins.attrNames rlmPackages == sources.primeAgent.rlmExtraPackages;
assert builtins.all consumerContractValid consumerSystems;
pkgs.runCommandLocal "check-ci-contract"
  {
    nativeBuildInputs = [
      pkgs.actionlint
      pkgs.bash
      pkgs.git
      pkgs.jq
      pkgs.gnutar
      pkgs.renovate
      pkgs.yq-go
    ];
  }
  ''
    export HOME="$TMPDIR/home"
    export XDG_CACHE_HOME="$TMPDIR/cache"
    mkdir -p "$HOME" "$XDG_CACHE_HOME"
    bash ${self}/scripts/fix-nix-hashes.sh validate ${self} ${effectiveContractFile}

    fixture="$TMPDIR/update-fixture"
    remote="$TMPDIR/update-remote.git"
    cp -R ${self} "$fixture"
    chmod -R u+w "$fixture"
    rm -rf "$fixture/.git"
    cd "$fixture"
    jq '.root as $root | .nodes["fixture-root"] = .nodes[$root] | del(.nodes[$root]) | .root = "fixture-root"' \
      flake.lock > "$TMPDIR/flake.lock"
    mv "$TMPDIR/flake.lock" flake.lock
    git init --quiet --initial-branch=renovate/ci-contract
    git config user.name "ci-contract"
    git config user.email "ci-contract@example.invalid"
    git add .
    git commit --quiet -m baseline
    base=$(git rev-parse HEAD)
    git init --quiet --bare --initial-branch=main "$remote"
    git remote add origin "$remote"
    git push --quiet -u origin HEAD

    remote_head() {
      git --git-dir="$remote" rev-parse refs/heads/renovate/ci-contract
    }

    assert_remote_head() {
      local localHead remoteHead
      localHead=$(git rev-parse HEAD)
      remoteHead=$(remote_head)
      if [ "$remoteHead" != "$localHead" ]; then
        echo "fixture push did not publish HEAD: local=$localHead remote=$remoteHead" >&2
        return 1
      fi
    }

    assert_remote_unchanged() {
      local expected=$1 actual
      actual=$(remote_head)
      if [ "$actual" != "$expected" ]; then
        echo "updater pushed unexpectedly: expected=$expected actual=$actual" >&2
        return 1
      fi
    }

    assert_tracked_clean() {
      if ! git diff --quiet; then
        echo "updater left unstaged changes" >&2
        git diff --stat >&2
        return 1
      fi
      if ! git diff --cached --quiet; then
        echo "updater left staged changes" >&2
        git diff --cached --stat >&2
        return 1
      fi
    }

    push_fixture_head() {
      git push --quiet origin HEAD
      assert_remote_head
    }

    before=$(git rev-parse HEAD)
    if bash ${self}/scripts/fix-nix-hashes.sh update refs/heads/ci-contract-missing \
      > "$TMPDIR/base-ref.log" 2>&1; then
      echo "update accepted a missing base ref" >&2
      exit 1
    fi
    grep -Fq "ERROR: base ref does not resolve to a commit:" "$TMPDIR/base-ref.log"
    test "$(git rev-parse HEAD)" = "$before"
    assert_tracked_clean
    assert_remote_head

    piPin=home-manager/modules/development/pins/pi.json
    ompPin=home-manager/modules/development/pins/omp.json
    primePin=home-manager/modules/development/pins/prime-agent.json
    mkdir -p "$TMPDIR/pi-source/package"
    printf '%s\n' '{"name":"pi-contract-fixture"}' > "$TMPDIR/pi-source/package/package.json"
    tar czf "$TMPDIR/pi-source.tgz" -C "$TMPDIR/pi-source" package
    export MOCK_PI_TARBALL="$TMPDIR/pi-source.tgz"
    primeFixture="$TMPDIR/prime-source/prime-agent-9.9.9"
    mkdir -p "$primeFixture/prime-agent-runtime" "$primeFixture/crates/pa-core/src/kernel/bootstrap/venv"
    printf '%s\n' '[workspace]' 'members = []' > "$primeFixture/Cargo.toml"
    printf '%s\n' 'version = 4' > "$primeFixture/Cargo.lock"
    cat > "$primeFixture/prime-agent-runtime/pyproject.toml" <<'EOF'
    [project]
    name = "prime-agent-runtime"
    version = "0.1.0"
    dependencies = ["mcp>=2,<3", "tyro"]
    EOF
    cat > "$primeFixture/prime-agent-runtime/uv.lock" <<EOF
    version = 1

    [[package]]
    name = "httpcore2"
    version = "20.0.1"
    wheels = [{ url = "https://files.pythonhosted.org/mock/httpcore2-20.0.1-py3-none-any.whl", hash = "sha256:$(printf 'a%.0s' {1..64})" }]

    [[package]]
    name = "httpx2"
    version = "20.0.2"
    wheels = [{ url = "https://files.pythonhosted.org/mock/httpx2-20.0.2-py3-none-any.whl", hash = "sha256:$(printf 'b%.0s' {1..64})" }]

    [[package]]
    name = "mcp"
    version = "20.0.3"
    wheels = [{ url = "https://files.pythonhosted.org/mock/mcp-20.0.3-py3-none-any.whl", hash = "sha256:$(printf 'c%.0s' {1..64})" }]

    [[package]]
    name = "mcp-types"
    version = "20.0.4"
    wheels = [{ url = "https://files.pythonhosted.org/mock/mcp_types-20.0.4-py3-none-any.whl", hash = "sha256:$(printf 'd%.0s' {1..64})" }]
    EOF
    tar czf "$TMPDIR/prime-source.tgz" -C "$TMPDIR/prime-source" prime-agent-9.9.9
    export MOCK_PRIME_TARBALL="$TMPDIR/prime-source.tgz"
    export PATH="${updateTestNix}/bin:${updateTestCurl}/bin:${updateTestNpm}/bin:$PATH"
    export MOCK_FLAKE_ROOT="$fixture"

    git switch --quiet -c main "$base"
    jq '.version = "9.9.10"' "$ompPin" > "$TMPDIR/base-omp.json"
    mv "$TMPDIR/base-omp.json" "$ompPin"
    git add "$ompPin"
    git commit --quiet -m "main: advance OMP independently"
    git push --quiet origin HEAD:main
    git switch --quiet renovate/ci-contract
    cp "$ompPin" "$TMPDIR/branch-omp.json"
    cp "$primePin" "$TMPDIR/branch-prime.json"

    jq '.version = "9.9.9"' "$piPin" > "$TMPDIR/pin.json"
    mv "$TMPDIR/pin.json" "$piPin"
    git add "$piPin"
    git commit --quiet -m "renovate: bump Pi"
    remoteBefore=$(remote_head)
    bash ${self}/scripts/fix-nix-hashes.sh update origin/main
    assert_remote_unchanged "$remoteBefore"
    push_fixture_head
    test "$(git rev-list --count "$base"..HEAD)" -eq 2
    jq -e '
      .name == "pi-contract-fixture"
      and .lockfileVersion == 3
      and .packages[""].name == "pi-contract-fixture"
    ' home-manager/modules/development/pi-package-lock.json >/dev/null
    cmp "$TMPDIR/branch-omp.json" "$ompPin"
    cmp "$TMPDIR/branch-prime.json" "$primePin"
    cp "$piPin" "$TMPDIR/updated-pi.json"
    cp home-manager/modules/development/pi-package-lock.json "$TMPDIR/updated-pi-lock.json"

    base=$(git rev-parse HEAD)
    jq '.version = "9.9.9"' "$ompPin" > "$TMPDIR/pin.json"
    mv "$TMPDIR/pin.json" "$ompPin"
    git add "$ompPin"
    git commit --quiet -m "renovate: bump OMP"
    remoteBefore=$(remote_head)
    bash ${self}/scripts/fix-nix-hashes.sh update "$base"
    assert_remote_unchanged "$remoteBefore"
    push_fixture_head
    test "$(git rev-list --count "$base"..HEAD)" -eq 2
    cmp "$TMPDIR/updated-pi.json" "$piPin"
    cmp "$TMPDIR/updated-pi-lock.json" home-manager/modules/development/pi-package-lock.json
    cmp "$TMPDIR/branch-prime.json" "$primePin"
    cp "$ompPin" "$TMPDIR/updated-omp.json"

    base=$(git rev-parse HEAD)
    jq '.version = "9.9.9"' "$primePin" > "$TMPDIR/pin.json"
    mv "$TMPDIR/pin.json" "$primePin"
    git add "$primePin"
    git commit --quiet -m "renovate: bump Prime Agent"
    remoteBefore=$(remote_head)
    bash ${self}/scripts/fix-nix-hashes.sh update "$base"
    assert_remote_unchanged "$remoteBefore"
    push_fixture_head
    test "$(git rev-list --count "$base"..HEAD)" -eq 2
    cmp "$TMPDIR/updated-pi.json" "$piPin"
    cmp "$TMPDIR/updated-pi-lock.json" home-manager/modules/development/pi-package-lock.json
    cmp "$TMPDIR/updated-omp.json" "$ompPin"
    jq -e '
      .python.httpcore2.version == "20.0.1"
      and .python.httpx2.version == "20.0.2"
      and .python.mcp.version == "20.0.3"
      and .python["mcp-types"].version == "20.0.4"
    ' "$primePin" >/dev/null
    before=$(git rev-parse HEAD)
    remoteBefore=$(remote_head)
    if MOCK_CARGO_WRONG_MISMATCH=1 bash ${self}/scripts/fix-nix-hashes.sh update "$base" \
      > "$TMPDIR/cargo-error.log" 2>&1; then
      echo "update accepted an unrelated dependency hash mismatch" >&2
      exit 1
    fi
    grep -Fq "cannot determine Prime Agent Cargo hash" "$TMPDIR/cargo-error.log"
    test "$(git rev-parse HEAD)" = "$before"
    assert_tracked_clean
    assert_remote_unchanged "$remoteBefore"
    base=$(git rev-parse HEAD)
    jq '.version = "9.9.10"' "$primePin" > "$TMPDIR/prime-agent.json"
    mv "$TMPDIR/prime-agent.json" "$primePin"
    git add "$primePin"
    git commit --quiet -m "renovate: bump Prime Agent with RLM drift"
    push_fixture_head
    remoteBefore=$(remote_head)
    before=$(git rev-parse HEAD)
    if MOCK_RLM_DRIFT=1 bash ${self}/scripts/fix-nix-hashes.sh update "$base" \
      > "$TMPDIR/drift.log" 2>&1; then
      echo "update accepted an unpinned Prime Agent RLM package" >&2
      exit 1
    fi
    grep -Fq "Prime Agent RLM package drift:" "$TMPDIR/drift.log"
    test "$(git rev-parse HEAD)" = "$before"
    assert_tracked_clean
    assert_remote_unchanged "$remoteBefore"
    if MOCK_SNAPSHOT_DRIFT=1 bash ${self}/scripts/fix-nix-hashes.sh update "$base" \
      > "$TMPDIR/snapshot.log" 2>&1; then
      echo "update accepted a changed Prime Agent snapshot requirement" >&2
      exit 1
    fi
    grep -Fq "Prime Agent snapshot requirement drift: upstream=cloudpickle" \
      "$TMPDIR/snapshot.log"
    test "$(git rev-parse HEAD)" = "$before"
    assert_tracked_clean
    assert_remote_unchanged "$remoteBefore"
    touch "$out"
  ''
