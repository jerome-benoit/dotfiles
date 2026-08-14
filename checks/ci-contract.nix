{ self, pkgs }:

let
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
