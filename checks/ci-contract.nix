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
      expectedKernelNames = lib.sort builtins.lessThan (
        [
          "jupyter-client"
          "rlm"
          sources.primeAgent.snapshotRequirement
        ]
        ++ sources.primeAgent.rlmExtraPackages
      );
      kernelPackages = primeAgentPackage.kernelPython.python.pkgs;
      expectedTyro = kernelPackages.tyro.overridePythonAttrs (_: {
        doCheck = false;
      });
      expectedScipy = kernelPackages.scipy.overridePythonAttrs (_: {
        doCheck = false;
      });
      expectedRlm = kernelPackages.buildPythonPackage {
        pname = "prime-agent-runtime";
        version = "0.1.0";
        pyproject = true;
        src = "${primeAgentPackage.src}/dist/prime-agent-runtime";
        build-system = [ kernelPackages.hatchling ];
        dependencies = [
          kernelPackages.ipykernel
          kernelPackages.nest-asyncio
          expectedTyro
        ];
        doCheck = false;
      };
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
      builtins.attrNames primeAgentPackage.kernelRequirements == expectedKernelNames
      &&
        kernelRequirementIdentity primeAgentPackage.kernelRequirements
        == kernelRequirementIdentity expectedKernelRequirements
      && builtins.all (
        requirement: builtins.elem requirement kernelEnvironmentPaths
      ) kernelRequirementPaths
      && usesIn primeAgentPackage.kernelPython primeAgentPackage.installPhase
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
    };
  };
  effectiveContractFile = pkgs.writeText "ci-effective-contract.json" (
    builtins.toJSON effectiveContract
  );
  ompSourceArchives = map pkgs.fetchurl (builtins.attrValues sources.omp.sources);
  updateTestNix = pkgs.writeShellScriptBin "nix" ''
    invocation=" $* "
    if [ "$#" -eq 4 ] && [ "$1" = run ] \
      && [ "$2" = "nixpkgs#prefetch-npm-deps" ] && [ "$3" = -- ] \
      && [ "$4" = ./package-lock.json ]; then
      hash=sha256-BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB=
    elif [ "$#" -eq 5 ] && [ "$1" = store ] && [ "$2" = prefetch-file ] \
      && [ "$3" = --unpack ] && [ "$4" = --json ]; then
      case "$5" in
        "https://registry.npmjs.org/@earendil-works/pi-coding-agent/-/pi-coding-agent-9.9.9.tgz")
          hash=sha256-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=
          ;;
        "https://github.com/PrimeIntellect-ai/prime-agent/releases/download/v9.9.9/prime-agent-9.9.9.tgz" | \
          "https://github.com/PrimeIntellect-ai/prime-agent/releases/download/v9.9.10/prime-agent-9.9.10.tgz")
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
    invocation=" $* "
    output=
    while [ "$#" -gt 0 ]; do
      if [ "$1" = -o ]; then
        output=$2
        shift 2
      else
        shift
      fi
    done
    if [ -n "$output" ]; then
      case "$invocation" in
        *"/v9.9.9/package-lock.json"* | *"/v9.9.10/package-lock.json"*) ;;
        *)
          echo "unexpected package-lock URL:$invocation" >&2
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
      }' > "$output"
    elif [[ $invocation == *"/v9.9.9/packages/coding-agent/src/core/kernel/bootstrap.ts"* ]] \
      || [[ $invocation == *"/v9.9.10/packages/coding-agent/src/core/kernel/bootstrap.ts"* ]]; then
      pin=home-manager/modules/development/pins/prime-agent.json
      jq -r '.rlmExtraPackages[] | "const dep = { uvArg: \"" + . + "\" };"' "$pin"
      if [ -n "''${MOCK_RLM_DRIFT:-}" ]; then
        printf '%s\n' 'const drift = { uvArg: "unpinned-package" };'
      fi
      if [ -n "''${MOCK_SNAPSHOT_DRIFT:-}" ]; then
        printf '%s\n' 'const STATE_SNAPSHOT_REQUIREMENT = "cloudpickle";'
      else
        jq -r '"const STATE_SNAPSHOT_REQUIREMENT = \"" + .snapshotRequirement + "\";"' "$pin"
      fi
    elif [[ $invocation == *"pi-coding-agent-9.9.9.tgz"* ]]; then
      cat "$MOCK_PI_TARBALL"
    else
      echo "unexpected curl invocation:$invocation" >&2
      exit 1
    fi
  '';
  updateTestNpm = pkgs.writeShellScriptBin "npm" ''
    if [ "$1" != install ]; then
      echo "unexpected npm invocation: $*" >&2
      exit 1
    fi
    printf '%s\n' '{"name":"pi-contract-fixture","lockfileVersion":3,"packages":{}}' > package-lock.json
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

    piPin=home-manager/modules/development/pins/pi.json
    ompPin=home-manager/modules/development/pins/omp.json
    primePin=home-manager/modules/development/pins/prime-agent.json
    mkdir -p "$TMPDIR/pi-source/package"
    printf '%s\n' '{"name":"pi-contract-fixture"}' > "$TMPDIR/pi-source/package/package.json"
    tar czf "$TMPDIR/pi-source.tgz" -C "$TMPDIR/pi-source" package
    export MOCK_PI_TARBALL="$TMPDIR/pi-source.tgz"
    export PATH="${updateTestNix}/bin:${updateTestCurl}/bin:${updateTestNpm}/bin:$PATH"

    jq '.version = "9.9.9"' "$piPin" > "$TMPDIR/pin.json"
    mv "$TMPDIR/pin.json" "$piPin"
    git add "$piPin"
    git commit --quiet -m "renovate: bump Pi"
    bash ${self}/scripts/fix-nix-hashes.sh update "$base"
    test "$(git rev-list --count "$base"..HEAD)" -eq 2
    jq -e \
      --arg src sha256-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA= \
      --arg npm sha256-BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB= \
      '.src.hash == $src and .npmDepsHash == $npm' "$piPin" >/dev/null
    jq -e '.name == "pi-contract-fixture" and .lockfileVersion == 3' \
      home-manager/modules/development/pi-package-lock.json >/dev/null

    base=$(git rev-parse HEAD)
    jq '.version = "9.9.9"' "$ompPin" > "$TMPDIR/pin.json"
    mv "$TMPDIR/pin.json" "$ompPin"
    git add "$ompPin"
    git commit --quiet -m "renovate: bump OMP"
    bash ${self}/scripts/fix-nix-hashes.sh update "$base"
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
    bash ${self}/scripts/fix-nix-hashes.sh update "$base"
    test "$(git rev-list --count "$base"..HEAD)" -eq 2
    jq -e \
      --arg src sha256-PPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPP= \
      --arg cmake sha256-CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC= \
      --arg photon sha256-HHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHH= \
      --arg undici sha256-UUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUU= \
      --arg zeromq sha256-ZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZ= '
        .src.hash == $src
        and .npm["cmake-ts"].version == "10.0.2"
        and .npm["cmake-ts"].hash == $cmake
        and .npm["@silvia-odwyer/photon-node"].version == "10.0.1"
        and .npm["@silvia-odwyer/photon-node"].hash == $photon
        and .npm.undici.version == "10.0.3"
        and .npm.undici.hash == $undici
        and .npm.zeromq.version == "10.0.4"
        and .npm.zeromq.hash == $zeromq
      ' "$primePin" >/dev/null

    base=$(git rev-parse HEAD)
    jq '.version = "9.9.10"' "$primePin" > "$TMPDIR/prime-agent.json"
    mv "$TMPDIR/prime-agent.json" "$primePin"
    git add "$primePin"
    git commit --quiet -m "renovate: bump Prime Agent with RLM drift"
    before=$(git rev-parse HEAD)
    if MOCK_RLM_DRIFT=1 bash ${self}/scripts/fix-nix-hashes.sh update "$base" \
      > "$TMPDIR/drift.log" 2>&1; then
      echo "update accepted an unpinned Prime Agent RLM package" >&2
      exit 1
    fi
    grep -Fq "Prime Agent RLM package drift:" "$TMPDIR/drift.log"
    test "$(git rev-parse HEAD)" = "$before"
    git diff --quiet
    if MOCK_SNAPSHOT_DRIFT=1 bash ${self}/scripts/fix-nix-hashes.sh update "$base" \
      > "$TMPDIR/snapshot.log" 2>&1; then
      echo "update accepted a changed Prime Agent snapshot requirement" >&2
      exit 1
    fi
    grep -Fq "Prime Agent snapshot requirement drift: upstream=cloudpickle" \
      "$TMPDIR/snapshot.log"
    test "$(git rev-parse HEAD)" = "$before"
    git diff --quiet
    touch "$out"
  ''
