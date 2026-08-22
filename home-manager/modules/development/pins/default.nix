{
  lib,
  fetchurl,
  fetchzip,
}:

let
  readPin = file: builtins.fromJSON (builtins.readFile file);
  renderVersion = template: version: builtins.replaceStrings [ "{version}" ] [ version ] template;

  piData = readPin ./pi.json;
  ompData = readPin ./omp.json;
  primeAgentData = readPin ./prime-agent.json;

  expectedOmpKeys = [
    "darwin-arm64"
    "linux-arm64"
    "linux-x64"
  ];
  expectedPrimeNpmKeys = [
    "@silvia-odwyer/photon-node"
    "cmake-ts"
    "undici"
    "zeromq"
  ];
  expectedPrimePythonKeys = [
    "httpcore2"
    "httpx2"
    "mcp"
    "mcp-types"
  ];
in
assert builtins.attrNames ompData.hashes == expectedOmpKeys;
assert builtins.attrNames primeAgentData.npm == expectedPrimeNpmKeys;
assert builtins.attrNames primeAgentData.python == expectedPrimePythonKeys;
assert
  primeAgentData.rlmExtraPackages == lib.sort builtins.lessThan primeAgentData.rlmExtraPackages;
{
  pi = {
    inherit (piData) version npmDepsHash;
    lockFileName = piData.lockFile;
    lockFile = ../. + "/${piData.lockFile}";
    src = fetchzip {
      url = renderVersion piData.src.urlTemplate piData.version;
      hash = piData.src.hash;
    };
  };

  omp = {
    inherit (ompData) version;
    sources = lib.mapAttrs (
      key: hash:
      fetchurl {
        url = builtins.replaceStrings [ "{version}" "{key}" ] [ ompData.version key ] ompData.urlTemplate;
        inherit hash;
      }
    ) ompData.hashes;
  };

  primeAgent = {
    inherit (primeAgentData) version rlmExtraPackages snapshotRequirement;
    src = fetchzip {
      url = renderVersion primeAgentData.src.urlTemplate primeAgentData.version;
      hash = primeAgentData.src.hash;
    };
    npm = lib.mapAttrs (
      _key: dependency:
      dependency
      // {
        src = fetchzip {
          url = renderVersion dependency.urlTemplate dependency.version;
          hash = dependency.hash;
        };
      }
    ) primeAgentData.npm;
    python = lib.mapAttrs (
      _key: dependency:
      dependency
      // {
        src = fetchurl {
          inherit (dependency) url hash;
        };
      }
    ) primeAgentData.python;
  };
}
