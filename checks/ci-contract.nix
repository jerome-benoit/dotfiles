{ self, pkgs }:

let
  lib = pkgs.lib;
  sources = import ../home-manager/modules/development/pins {
    inherit (pkgs) lib;
    fetchurl = arguments: arguments;
    fetchzip = arguments: arguments;
  };
  dummyPythonPackages = pkgs.lib.genAttrs [
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
  homeConfigurations = lib.filterAttrs (
    _name: home: home.pkgs.stdenv.hostPlatform.system == pkgs.stdenv.hostPlatform.system
  ) self.homeConfigurations;
  consumerModules =
    (builtins.head (builtins.attrValues homeConfigurations)).config.modules.development;
  piPackage = consumerModules.pi.package;
  ompPackage = consumerModules.omp.package;
  primeAgentPackage = consumerModules.primeAgent.package;
  primeRuntimeSources = primeAgentPackage.runtimeSources;
  platformKey = "${pkgs.stdenv.hostPlatform.node.platform}-${pkgs.stdenv.hostPlatform.node.arch}";
  plainString = builtins.unsafeDiscardStringContext;
  usesIn = dependency: script: lib.hasInfix (plainString (toString dependency)) (plainString script);
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
      npm = pkgs.lib.mapAttrs (_key: dependency: {
        inherit (dependency) version src;
      }) sources.primeAgent.npm;
    };
  };
  effectiveContractFile = pkgs.writeText "ci-effective-contract.json" (
    builtins.toJSON effectiveContract
  );
in
assert builtins.attrNames rlmPackages == sources.primeAgent.rlmExtraPackages;
assert lib.assertMsg (
  homeConfigurations != { }
) "ci-contract: no Home Manager consumer for this system";
assert lib.assertMsg (
  piPackage.version == sources.pi.version
) "ci-contract: pi.nix ignores the pinned version";
assert lib.assertMsg (
  piPackage.src.url == sources.pi.src.url && piPackage.src.outputHash == sources.pi.src.hash
) "ci-contract: pi.nix ignores the pinned source";
assert lib.assertMsg (
  piPackage.npmDeps.outputHash == sources.pi.npmDepsHash
) "ci-contract: pi.nix ignores the pinned npm hash";
assert lib.assertMsg (
  lib.hasSuffix "-${sources.pi.lockFileName}" (plainString piPackage.contractLockStorePath)
  &&
    builtins.hashFile "sha256" piPackage.contractLockFile
    == builtins.hashFile "sha256" sources.pi.lockFile
  && usesIn piPackage.contractLockStorePath piPackage.postPatch
  && usesIn piPackage.contractLockStorePath piPackage.npmDeps.postPatch
) "ci-contract: pi.nix does not consume the pinned lock in both npm phases";
assert lib.assertMsg (
  ompPackage.version == sources.omp.version
) "ci-contract: omp.nix ignores the pinned version";
assert lib.assertMsg (
  ompPackage.src.url == sources.omp.sources.${platformKey}.url
  && ompPackage.src.outputHash == sources.omp.sources.${platformKey}.hash
) "ci-contract: omp.nix ignores the pinned platform source";
assert lib.assertMsg (
  primeAgentPackage.version == sources.primeAgent.version
) "ci-contract: prime-agent.nix ignores the pinned version";
assert lib.assertMsg (
  primeAgentPackage.src.url == sources.primeAgent.src.url
  && primeAgentPackage.src.outputHash == sources.primeAgent.src.hash
) "ci-contract: prime-agent.nix ignores the pinned source";
assert lib.assertMsg (
  builtins.attrNames primeRuntimeSources == builtins.attrNames sources.primeAgent.npm
) "ci-contract: prime-agent.nix runtime source set differs from its pins";
assert lib.assertMsg (
  primeRuntimeSources.zeromq.version == sources.primeAgent.npm.zeromq.version
  && primeRuntimeSources.zeromq.src.url == sources.primeAgent.npm.zeromq.src.url
  && primeRuntimeSources.zeromq.src.outputHash == sources.primeAgent.npm.zeromq.src.hash
) "ci-contract: prime-agent.nix ignores the pinned zeromq dependency";
assert lib.assertMsg (builtins.all
  (
    key:
    let
      installed = primeRuntimeSources.${key};
      actual = if key == "zeromq" then installed.src else installed;
      expected = sources.primeAgent.npm.${key}.src;
    in
    actual.url == expected.url
    && actual.outputHash == expected.hash
    && usesIn installed primeAgentPackage.installPhase
  )
  (builtins.attrNames primeRuntimeSources)
) "ci-contract: prime-agent.nix does not install every pinned runtime source";
assert lib.assertMsg (
  usesIn primeAgentPackage.kernelPython primeAgentPackage.installPhase
  && usesIn primeAgentPackage.kernelPython primeAgentPackage.preInstallCheck
) "ci-contract: prime-agent.nix does not consume its validated kernel environment";
pkgs.runCommandLocal "check-ci-contract"
  {
    nativeBuildInputs = [
      pkgs.actionlint
      pkgs.bash
      pkgs.git
      pkgs.jq
      pkgs.renovate
      pkgs.yq-go
    ];
  }
  ''
    export HOME="$TMPDIR/home"
    export XDG_CACHE_HOME="$TMPDIR/cache"
    mkdir -p "$HOME" "$XDG_CACHE_HOME"
    bash ${self}/scripts/fix-nix-hashes.sh validate ${self} ${effectiveContractFile}
    touch "$out"
  ''
