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
  primeAgentRuntimeRoot = "${primeAgentSource}/dist/prime-agent-runtime";
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

  plainString = builtins.unsafeDiscardStringContext;
  usesIn = dependency: script: lib.hasInfix (plainString (toString dependency)) (plainString script);
  hasExactTrimmedLine =
    expected: script: builtins.elem expected (map lib.trim (lib.splitString "\n" (plainString script)));
  consumerContractValid =
    system:
    let
      packages = consumerPackages.${system};
      piPackage = packages.pi;
      ompPackage = packages.omp;
      primeAgentPackage = packages.primeAgent;
      primeRuntimeSources = primeAgentPackage.runtimeSources;
      platformKey = platformKeys.${system};
      lockStorePath = plainString piPackage.contractLockStorePath;
      expectedPiPostPatch = "rm -f npm-shrinkwrap.json\ncp ${lockStorePath} package-lock.json";
      expectedPiNpmPostPatch = "cp ${lockStorePath} package-lock.json";
      expectedKernelAssignment = lib.trim ''
        --set PRIME_AGENT_KERNEL_PYTHON ${primeAgentPackage.kernelPython}/bin/python3 \
      '';
      expectedKernelNames = lib.sort builtins.lessThan (
        [
          "jupyter-client"
          "rlm"
          sources.primeAgent.snapshotRequirement
        ]
        ++ sources.primeAgent.rlmExtraPackages
      );
      kernelPackages = primeAgentPackage.kernelPython.python.pkgs;
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
      expectedTyro = kernelPackages.tyro.overridePythonAttrs (_: {
        doCheck = false;
      });
      expectedScipy = kernelPackages.scipy.overridePythonAttrs (_: {
        doCheck = false;
      });
      expectedMappedKernelRequirements = lib.genAttrs sources.primeAgent.rlmExtraPackages (
        name:
        if name == "scipy" then
          expectedScipy
        else if name == "tyro" then
          expectedTyro
        else
          kernelPackages.${name}
      );
      expectedKernelRequirements = expectedMappedKernelRequirements // {
        rlm = expectedRlm;
        "${sources.primeAgent.snapshotRequirement}" =
          kernelPackages.${sources.primeAgent.snapshotRequirement};
        jupyter-client = kernelPackages.jupyter-client;
      };
      kernelRequirementIdentity =
        requirements: lib.mapAttrs (_name: requirement: plainString (toString requirement)) requirements;
      kernelRequirementPaths = map toString (builtins.attrValues primeAgentPackage.kernelRequirements);
      kernelEnvironmentPaths = map toString primeAgentPackage.kernelPython.paths;
      runtimeCopyCommands = [
        ''cp -r ${primeRuntimeSources.zeromq} "$nm/zeromq"''
        ''cp -r ${primeRuntimeSources.cmake-ts}/. "$nm/cmake-ts/"''
        ''cp -r ${primeRuntimeSources."@silvia-odwyer/photon-node"}/. "$nm/@silvia-odwyer/photon-node/"''
        ''cp -r ${primeRuntimeSources.undici}/. "$nm/undici/"''
      ];
      runtimeSourceValid =
        key:
        let
          installed = primeRuntimeSources.${key};
          actual = if key == "zeromq" then installed.src else installed;
          expected = sources.primeAgent.npm.${key}.src;
        in
        actual.url == expected.url && actual.outputHash == expected.hash;
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
      piPackage.src.url == sources.pi.src.url && piPackage.src.outputHash == sources.pi.src.hash
    ) (message "pi.nix ignores the pinned source")
    && lib.assertMsg (piPackage.npmDeps.outputHash == sources.pi.npmDepsHash) (
      message "pi.nix ignores the pinned npm hash"
    )
    && lib.assertMsg (
      builtins.elem piPackage packages.installed.packages
      && builtins.elem ompPackage packages.installed.omp
      && builtins.elem primeAgentPackage packages.installed.primeAgent
    ) (message "an enabled development module does not install its configured package")
    && lib.assertMsg (
      lib.hasSuffix "-${sources.pi.lockFileName}" lockStorePath
      &&
        builtins.hashFile "sha256" piPackage.contractLockFile
        == builtins.hashFile "sha256" sources.pi.lockFile
      && plainString (lib.trim piPackage.postPatch) == expectedPiPostPatch
      && plainString (lib.trim piPackage.npmDeps.postPatch) == expectedPiNpmPostPatch
    ) (message "pi.nix does not copy the pinned lock to package-lock.json in both npm phases")
    && lib.assertMsg (ompPackage.version == sources.omp.version) (
      message "omp.nix ignores the pinned version"
    )
    && lib.assertMsg (
      ompPackage.src.url == sources.omp.sources.${platformKey}.url
      && ompPackage.src.outputHash == sources.omp.sources.${platformKey}.hash
    ) (message "omp.nix ignores the pinned platform source")
    && lib.assertMsg (primeAgentPackage.version == sources.primeAgent.version) (
      message "prime-agent.nix ignores the pinned version"
    )
    && lib.assertMsg (
      primeAgentPackage.src.url == sources.primeAgent.src.url
      && primeAgentPackage.src.outputHash == sources.primeAgent.src.hash
    ) (message "prime-agent.nix ignores the pinned source")
    && lib.assertMsg (
      builtins.attrNames primeRuntimeSources == builtins.attrNames sources.primeAgent.npm
      && builtins.all runtimeSourceValid (builtins.attrNames primeRuntimeSources)
      && primeRuntimeSources.zeromq.version == sources.primeAgent.npm.zeromq.version
    ) (message "prime-agent.nix runtime source set differs from its pins")
    && lib.assertMsg (builtins.all (command: usesIn command primeAgentPackage.installPhase)
      runtimeCopyCommands
    ) (message "prime-agent.nix does not install every runtime source at its canonical destination")
    && lib.assertMsg (
      builtins.attrNames pythonRuntimePackages == builtins.attrNames sources.primeAgent.python
      && builtins.all pythonRuntimePackageValid (builtins.attrNames pythonRuntimePackages)
      &&
        primeAgentPackage.runtimeProject
        == "${primeAgentPackage.src}/dist/prime-agent-runtime/pyproject.toml"
      && primeAgentPackage.runtimeLock == "${primeAgentPackage.src}/dist/prime-agent-runtime/uv.lock"
      && runtimeProject.project.name == "prime-agent-runtime"
      && runtimeProject.project.version == expectedRlm.version
      && expectedRlm.src == "${primeAgentPackage.src}/dist/prime-agent-runtime"
      && declaredRuntimeDependencies == actualRuntimeDependencies
      && builtins.elem pythonRuntimePackages.mcp expectedRlm.dependencies
      && lib.versionAtLeast pythonRuntimePackages.mcp.version "2"
      && lib.versionOlder pythonRuntimePackages.mcp.version "3"
    ) (message "prime-agent.nix runtime package differs from the release Python lock")
    && lib.assertMsg (
      builtins.attrNames primeAgentPackage.kernelRequirements == expectedKernelNames
      &&
        kernelRequirementIdentity primeAgentPackage.kernelRequirements
        == kernelRequirementIdentity expectedKernelRequirements
      && builtins.all (
        requirement: builtins.elem requirement kernelEnvironmentPaths
      ) kernelRequirementPaths
      && hasExactTrimmedLine expectedKernelAssignment primeAgentPackage.installPhase
      && usesIn primeAgentPackage.kernelPython primeAgentPackage.preInstallCheck
    ) (message "prime-agent.nix kernel environment differs from its pinned requirements");

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
        rlmExtraPackages
        snapshotRequirement
        ;
      npm = lib.mapAttrs (_key: dependency: {
        inherit (dependency) version src;
      }) sources.primeAgent.npm;
      python = lib.mapAttrs (_key: dependency: {
        inherit (dependency) version src;
      }) sources.primeAgent.python;
    };
  };
  effectiveContractFile = pkgs.writeText "ci-effective-contract.json" (
    builtins.toJSON effectiveContract
  );
  ompSourceArchives = map pkgs.fetchurl (builtins.attrValues sources.omp.sources);
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
    dependency: ''const dep = { uvArg: "${dependency}" };''
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
        file://*)
          hash=sha256-PPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPP=
          ;;
        "https://registry.npmjs.org/cmake-ts/-/cmake-ts-10.0.2.tgz")
          hash=sha256-CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC=
          ;;
        "https://registry.npmjs.org/@silvia-odwyer/photon-node/-/photon-node-10.0.1.tgz")
          hash=sha256-HHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHH=
          ;;
        "https://registry.npmjs.org/undici/-/undici-10.0.3.tgz")
          hash=sha256-UUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUU=
          ;;
        "https://registry.npmjs.org/zeromq/-/zeromq-10.0.4.tgz")
          hash=sha256-ZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZ=
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
    elif [ "$#" -eq 3 ] && [ "$1" = build ] && [ "$2" = --no-link ] \
      && [ "$3" = ".#homeConfigurations.almalinux.config.modules.development.openspec.package" ]; then
      refreshed=sha256-OOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOO=
      if grep -Fqx '  pnpmDepsHash = "'"$refreshed"'";' "$MOCK_OPENSPEC_MODULE"; then
        exit
      fi
      printf '%s\n' \
        'error: hash mismatch in fixed-output derivation' \
        '  specified: sha256-SSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSS=' \
        "       got: $refreshed" >&2
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
        "https://raw.githubusercontent.com/PrimeIntellect-ai/prime-agent/v9.9.9/package-lock.json" | \
          "https://raw.githubusercontent.com/PrimeIntellect-ai/prime-agent/v9.9.10/package-lock.json")
          ;;
        "https://github.com/PrimeIntellect-ai/prime-agent/releases/download/v9.9.9/prime-agent-9.9.9.tgz" | \
          "https://github.com/PrimeIntellect-ai/prime-agent/releases/download/v9.9.10/prime-agent-9.9.10.tgz")
          cat "$MOCK_PRIME_TARBALL" > "$4"
          exit
          ;;
        *)
          echo "unexpected package-lock URL:$2" >&2
          exit 1
          ;;
      esac
      jq -n '{
        packages: {
          "node_modules/@silvia-odwyer/photon-node": { version: "10.0.1" },
          "node_modules/cmake-ts": { version: "10.0.2" },
          "node_modules/undici": { version: "10.0.3" },
          "node_modules/zeromq": { version: "10.0.4" }
        }
      }' > "$4"
    elif [ "$#" -eq 2 ] && [ "$1" = -sfSL ]; then
      case "$2" in
        "https://raw.githubusercontent.com/PrimeIntellect-ai/prime-agent/v9.9.9/packages/coding-agent/src/core/kernel/bootstrap.ts" | \
          "https://raw.githubusercontent.com/PrimeIntellect-ai/prime-agent/v9.9.10/packages/coding-agent/src/core/kernel/bootstrap.ts")
          printf '%s\n' ${lib.escapeShellArg updateTestBootstrap}
          if [ -n "''${MOCK_RLM_DRIFT:-}" ]; then
            printf '%s\n' 'const drift = { uvArg: "unpinned-package" };'
          fi
          if [ -n "''${MOCK_SNAPSHOT_DRIFT:-}" ]; then
            printf '%s\n' 'const STATE_SNAPSHOT_REQUIREMENT = "cloudpickle";'
          else
            printf '%s\n' 'const STATE_SNAPSHOT_REQUIREMENT = "dill";'
          fi
          ;;
        "https://registry.npmjs.org/@earendil-works/pi-coding-agent/-/pi-coding-agent-9.9.9.tgz")
          cat "$MOCK_PI_TARBALL"
          ;;
        *)
          echo "unexpected curl URL:$2" >&2
          exit 1
          ;;
      esac
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
    for archive in ${lib.escapeShellArgs (map toString ompSourceArchives)}; do
      test -f "$archive"
    done
    export XDG_CACHE_HOME="$TMPDIR/cache"
    mkdir -p "$HOME" "$XDG_CACHE_HOME"
    bash ${self}/scripts/fix-nix-hashes.sh validate ${self} ${effectiveContractFile}

    fixture="$TMPDIR/update-fixture"
    remote="$TMPDIR/update-remote.git"
    cp -R ${self} "$fixture"
    chmod -R u+w "$fixture"
    cd "$fixture"
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
    openspecModule=home-manager/modules/development/openspec.nix
    flakeLock=flake.lock
    mkdir -p "$TMPDIR/pi-source/package"
    printf '%s\n' '{"name":"pi-contract-fixture"}' > "$TMPDIR/pi-source/package/package.json"
    tar czf "$TMPDIR/pi-source.tgz" -C "$TMPDIR/pi-source" package
    export MOCK_PI_TARBALL="$TMPDIR/pi-source.tgz"
    mkdir -p "$TMPDIR/prime-source/package/dist/prime-agent-runtime"
    cat > "$TMPDIR/prime-source/package/dist/prime-agent-runtime/pyproject.toml" <<'EOF'
    [project]
    name = "prime-agent-runtime"
    version = "0.1.0"
    dependencies = ["ipykernel", "mcp>=2,<3", "nest-asyncio", "tyro"]
    EOF
    cat > "$TMPDIR/prime-source/package/dist/prime-agent-runtime/uv.lock" <<EOF
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
    tar czf "$TMPDIR/prime-source.tgz" -C "$TMPDIR/prime-source" package
    export MOCK_PRIME_TARBALL="$TMPDIR/prime-source.tgz"
    export PATH="${updateTestNix}/bin:${updateTestCurl}/bin:${updateTestNpm}/bin:$PATH"
    export MOCK_FLAKE_ROOT="$fixture"
    export MOCK_OPENSPEC_MODULE="$fixture/$openspecModule"

    git switch --quiet -c main "$base"
    jq '.version = "9.9.10"' "$ompPin" > "$TMPDIR/base-omp.json"
    mv "$TMPDIR/base-omp.json" "$ompPin"
    git add "$ompPin"
    git commit --quiet -m "main: advance OMP independently"
    git push --quiet origin HEAD:main
    git switch --quiet renovate/ci-contract
    cp "$ompPin" "$TMPDIR/branch-omp.json"

    jq '.version = "9.9.9"' "$piPin" > "$TMPDIR/pin.json"
    mv "$TMPDIR/pin.json" "$piPin"
    git add "$piPin"
    git commit --quiet -m "renovate: bump Pi"
    remoteBefore=$(remote_head)
    bash ${self}/scripts/fix-nix-hashes.sh update origin/main
    assert_remote_unchanged "$remoteBefore"
    push_fixture_head
    test "$(git rev-list --count "$base"..HEAD)" -eq 2
    jq -e \
      --arg src sha256-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA= \
      --arg npm sha256-BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB= \
      '.src.hash == $src and .npmDepsHash == $npm' "$piPin" >/dev/null
    jq -e '
      .name == "pi-contract-fixture"
      and .lockfileVersion == 3
      and .packages[""].name == "pi-contract-fixture"
    ' home-manager/modules/development/pi-package-lock.json >/dev/null
    cmp "$TMPDIR/branch-omp.json" "$ompPin"

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
    jq -e \
      --arg darwin sha256-DDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDD= \
      --arg arm sha256-LLLLLLLLLLLLLLLLLLLLLLLLLLLLLLLLLLLLLLLLLLL= \
      --arg x64 sha256-XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX= '
        .hashes == {
          "darwin-arm64": $darwin,
          "linux-arm64": $arm,
          "linux-x64": $x64
        }
      ' "$ompPin" >/dev/null

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
    jq -e \
      --arg src sha256-PPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPP= \
      --arg cmake sha256-CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC= \
      --arg photon sha256-HHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHH= \
      --arg undici sha256-UUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUU= \
      --arg zeromq sha256-ZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZ= \
      --arg httpcore2 sha256-1111111111111111111111111111111111111111111= \
      --arg httpx2 sha256-2222222222222222222222222222222222222222222= \
      --arg mcp sha256-3333333333333333333333333333333333333333333= \
      --arg mcpTypes sha256-4444444444444444444444444444444444444444444= '
        .src.hash == $src
        and .npm["cmake-ts"].version == "10.0.2"
        and .npm["cmake-ts"].hash == $cmake
        and .npm["@silvia-odwyer/photon-node"].version == "10.0.1"
        and .npm["@silvia-odwyer/photon-node"].hash == $photon
        and .npm.undici.version == "10.0.3"
        and .npm.undici.hash == $undici
        and .npm.zeromq.version == "10.0.4"
        and .npm.zeromq.hash == $zeromq
        and .python.httpcore2.version == "20.0.1"
        and .python.httpcore2.url == "https://files.pythonhosted.org/mock/httpcore2-20.0.1-py3-none-any.whl"
        and .python.httpcore2.hash == $httpcore2
        and .python.httpx2.version == "20.0.2"
        and .python.httpx2.hash == $httpx2
        and .python.mcp.version == "20.0.3"
        and .python.mcp.hash == $mcp
        and .python["mcp-types"].version == "20.0.4"
        and .python["mcp-types"].hash == $mcpTypes
      ' "$primePin" >/dev/null
    base=$(git rev-parse HEAD)
    cp "$openspecModule" "$TMPDIR/openspec-before.nix"
    jq '.nodes.nixpkgs.locked.lastModified += 1' "$flakeLock" > "$TMPDIR/flake.lock"
    mv "$TMPDIR/flake.lock" "$flakeLock"
    git add "$flakeLock"
    git commit --quiet -m "renovate: bump unrelated flake input"
    remoteBefore=$(remote_head)
    bash ${self}/scripts/fix-nix-hashes.sh update "$base" > "$TMPDIR/unrelated-flake.log"
    grep -Fqx "No supported dependency changes detected" "$TMPDIR/unrelated-flake.log"
    test "$(git rev-list --count "$base"..HEAD)" -eq 1
    cmp "$TMPDIR/openspec-before.nix" "$openspecModule"
    assert_remote_unchanged "$remoteBefore"
    push_fixture_head

    base=$(git rev-parse HEAD)
    jq '.nodes.openspec.locked.lastModified += 1' "$flakeLock" > "$TMPDIR/flake.lock"
    mv "$TMPDIR/flake.lock" "$flakeLock"
    git add "$flakeLock"
    git commit --quiet -m "renovate: bump OpenSpec"
    remoteBefore=$(remote_head)
    bash ${self}/scripts/fix-nix-hashes.sh update "$base" > "$TMPDIR/openspec.log"
    grep -Fqx \
      "Updated OpenSpec pnpm hash to sha256-OOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOO=" \
      "$TMPDIR/openspec.log"
    assert_remote_unchanged "$remoteBefore"
    push_fixture_head
    test "$(git rev-list --count "$base"..HEAD)" -eq 2
    grep -Fqx \
      '  pnpmDepsHash = "sha256-OOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOO=";' \
      "$openspecModule"
    before=$(git rev-parse HEAD)
    bash ${self}/scripts/fix-nix-hashes.sh update "$base" > "$TMPDIR/openspec-repeat.log"
    grep -Fqx "OpenSpec pnpm hash is current" "$TMPDIR/openspec-repeat.log"
    test "$(git rev-parse HEAD)" = "$before"
    assert_tracked_clean

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
