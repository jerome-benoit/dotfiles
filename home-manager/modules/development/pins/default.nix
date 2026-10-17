{
  lib,
  fetchurl,
  fetchzip,
}:

let
  readPin = file: builtins.fromJSON (builtins.readFile file);
  renderVersion = template: version: builtins.replaceStrings [ "{version}" ] [ version ] template;

  ompData = readPin ./omp.json;
  primeAgentData = readPin ./prime-agent.json;
  cavemanData = readPin ./caveman.json;

  expectedOmpKeys = [
    "darwin-arm64"
    "linux-arm64"
    "linux-x64"
  ];
  expectedPrimePythonKeys = [
    "httpcore2"
    "httpx2"
    "mcp"
    "mcp-types"
  ];
in
assert builtins.attrNames ompData.hashes == expectedOmpKeys;
assert builtins.attrNames primeAgentData.python == expectedPrimePythonKeys;
assert
  primeAgentData.rlmExtraPackages == lib.sort builtins.lessThan primeAgentData.rlmExtraPackages;
{
  caveman = {
    inherit (cavemanData) version;
    cli = fetchurl {
      url = renderVersion cavemanData.cli.urlTemplate cavemanData.version;
      hash = cavemanData.cli.hash;
    };
    src = fetchzip {
      url = renderVersion cavemanData.src.urlTemplate cavemanData.version;
      hash = cavemanData.src.hash;
    };
    licenses = lib.mapAttrs (
      name: hash:
      fetchurl {
        url =
          builtins.replaceStrings [ "{version}" "{name}" ] [ cavemanData.version name ]
            cavemanData.licenses.urlTemplate;
        inherit hash;
      }
    ) cavemanData.licenses.hashes;
    runtime = lib.mapAttrs (
      platform: binaries:
      lib.mapAttrs (
        name: hash:
        fetchurl {
          url =
            builtins.replaceStrings [ "{version}" "{name}" "{platform}" ] [ cavemanData.version name platform ]
              cavemanData.runtime.urlTemplate;
          inherit hash;
        }
      ) binaries
    ) cavemanData.runtime.hashes;
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
    inherit (primeAgentData)
      version
      cargoHash
      rlmExtraPackages
      snapshotRequirement
      ;
    src = fetchzip {
      url = renderVersion primeAgentData.src.urlTemplate primeAgentData.version;
      hash = primeAgentData.src.hash;
    };
    bundledCatalogs = fetchzip {
      inherit (primeAgentData.bundledCatalogs) url hash;
    };
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
