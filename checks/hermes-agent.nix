{
  pkgs,
  home-manager,
  inputs,
}:
let
  lib = pkgs.lib;
  fixtureHome = "/home/hermes-check";
  plugin = "${inputs.hermes-labs-plugins}/github-copilot";
  configuration = home-manager.lib.homeManagerConfiguration {
    inherit pkgs;
    extraSpecialArgs = { inherit inputs; };
    modules = [
      inputs.hermes-agent.homeManagerModules.default
      ../home-manager/modules/core/lib.nix
      ../home-manager/modules/development/hermes-agent.nix
      ({ lib, ... }: {
        options = {
          modules.core.gpu.acceleration = lib.mkOption {
            type = lib.types.str;
            default = "none";
          };
          sops.secrets = lib.mkOption {
            type = lib.types.attrs;
            default.hermes-env.path = "${fixtureHome}/secret.env";
          };
        };
        config = {
          home = {
            username = "hermes-check";
            homeDirectory = fixtureHome;
            stateVersion = "26.05";
          };
          modules.development.hermesAgent = {
            enable = true;
            plugins.github-copilot = plugin;
          };
        };
      })
    ];
  };
  evaluate = settings: configuration.extendModules { modules = [ settings ]; };
  accepts = settings: (builtins.tryEval (evaluate settings).activationPackage.drvPath).success;
  externalHomes = [
    "/srv/hermes"
    "${fixtureHome}-other/.hermes"
    "${fixtureHome}/../outside"
  ];
  nonCanonicalHomes = [
    ""
    "relative-hermes"
    "${fixtureHome}/.hermes/"
    "${fixtureHome}/./.hermes"
    "${fixtureHome}//.hermes"
    "${fixtureHome}/cache/../.hermes"
    "/home//hermes-check/.hermes"
  ];
  check = label: condition: lib.assertMsg condition "Hermes plugin regression: ${label}";
in
assert lib.all (condition: condition) [
  (check "external Hermes homes fail before activation" (
    lib.all (hermesHome: !accepts { services.hermes-agent.hermesHome = hermesHome; }) externalHomes
  ))
  (check "ambiguous path spellings fail before activation" (
    lib.all (hermesHome: !accepts { services.hermes-agent.hermesHome = hermesHome; }) nonCanonicalHomes
  ))
  (check "non-canonical HOME fails before activation" (
    !accepts { home.homeDirectory = lib.mkForce "${fixtureHome}/../hermes-check"; }
  ))
  (check "canonical homes and custom subdirectories remain supported" (
    lib.all (hermesHome: accepts { services.hermes-agent.hermesHome = hermesHome; }) [
      fixtureHome
      "${fixtureHome}/.hermes"
      "${fixtureHome}/custom hermes"
    ]
  ))
  (check "root HOME retains valid plugin destinations" (
    lib.all
      (
        hermesHome:
        accepts {
          home.homeDirectory = lib.mkForce "/";
          services.hermes-agent.hermesHome = hermesHome;
        }
      )
      [
        "/"
        "/state/hermes"
      ]
  ))
  (check "empty plugins preserve existing Hermes home support" (
    lib.all (
      hermesHome:
      accepts {
        services.hermes-agent.hermesHome = hermesHome;
        modules.development.hermesAgent.plugins = lib.mkForce { };
      }
    ) (externalHomes ++ nonCanonicalHomes)
  ))
  (check "disabled integration does not restrict Hermes home" (
    lib.all (
      hermesHome:
      accepts {
        services.hermes-agent.hermesHome = hermesHome;
        modules.development.hermesAgent.enable = lib.mkForce false;
      }
    ) (externalHomes ++ nonCanonicalHomes)
  ))
];
pkgs.runCommand "check-hermes-plugin-home" { } ''
  echo "hermes-agent: plugin home boundaries and disabled/empty configurations passed"
  touch "$out"
''
