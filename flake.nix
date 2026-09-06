{
  description = "Fraggle's nix flakes configuration";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs?ref=nixpkgs-unstable";
    home-manager = {
      url = "github:nix-community/home-manager";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    sops-nix = {
      url = "github:Mic92/sops-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    opencode = {
      url = "github:anomalyco/opencode";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    opencode-nvim = {
      url = "github:NickvanDyke/opencode.nvim";
      flake = false;
    };
    agent-of-empires = {
      url = "github:agent-of-empires/agent-of-empires";
      inputs = {
        nixpkgs.follows = "nixpkgs";
        flake-parts.follows = "flake-parts";
      };
    };
    herdr = {
      url = "github:ogulcancelik/herdr";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    agtx = {
      url = "github:fynnfluegge/agtx";
      flake = false;
    };
    openspec = {
      url = "github:Fission-AI/OpenSpec";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    qmd = {
      url = "github:tobi/qmd";
      inputs = {
        nixpkgs.follows = "nixpkgs";
        flake-utils.follows = "flake-utils";
      };
    };
    colibri = {
      url = "github:JustVugg/colibri";
      inputs = {
        nixpkgs.follows = "nixpkgs";
        flake-utils.follows = "flake-utils";
      };
    };
    nix-openclaw = {
      url = "github:openclaw/nix-openclaw";
      inputs = {
        nixpkgs.follows = "nixpkgs";
        home-manager.follows = "home-manager";
        flake-utils.follows = "flake-utils";
        nix-openclaw-tools.follows = "nix-openclaw-tools";
        qmd.follows = "qmd";
      };
    };
    flake-utils.url = "github:numtide/flake-utils";
    flake-parts.url = "github:hercules-ci/flake-parts";
    nix-openclaw-tools = {
      url = "github:openclaw/nix-openclaw-tools";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    # See .serena/memories/processes/hermes_agent_sync_main_patched.md
    hermes-agent = {
      url = "github:jerome-benoit/hermes-agent/main-patched";
      inputs = {
        nixpkgs.follows = "nixpkgs";
        flake-parts.follows = "flake-parts";
        home-manager.follows = "home-manager";
        pyproject-nix.follows = "pyproject-nix";
        uv2nix.follows = "uv2nix";
        pyproject-build-systems.follows = "pyproject-build-systems";
      };
    };
    pyproject-nix = {
      url = "github:pyproject-nix/pyproject.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    uv2nix = {
      url = "github:pyproject-nix/uv2nix";
      inputs = {
        nixpkgs.follows = "nixpkgs";
        pyproject-nix.follows = "pyproject-nix";
      };
    };
    pyproject-build-systems = {
      url = "github:pyproject-nix/build-system-pkgs";
      inputs = {
        nixpkgs.follows = "nixpkgs";
        pyproject-nix.follows = "pyproject-nix";
        uv2nix.follows = "uv2nix";
      };
    };
  };

  outputs =
    {
      self,
      nixpkgs,
      home-manager,
      ...
    }@inputs:
    let
      constants = import ./constants.nix;
      privateConfig = import ./secrets/default.nix;
      forAllSystems = nixpkgs.lib.genAttrs (
        nixpkgs.lib.mapAttrsToList (_: sys: sys.arch) constants.systems
      );

      localOverlays = [
        inputs.nix-openclaw.overlays.default
        (
          _: prev:
          nixpkgs.lib.optionalAttrs prev.stdenv.hostPlatform.isDarwin {
            # agent tests break on hardcoded /tmp/crush-test in darwin's shared /tmp.
            crush = prev.crush.overrideAttrs (previousAttrs: {
              postPatch = (previousAttrs.postPatch or "") + ''
                substituteInPlace internal/agent/common_test.go \
                  --replace-fail '"/tmp/crush-test/"' 'os.TempDir()'
              '';
            });
          }
        )
      ];

      mkPkgs =
        arch:
        let
          isDarwin = nixpkgs.legacyPackages.${arch}.stdenv.hostPlatform.isDarwin;
        in
        import nixpkgs {
          system = arch;
          overlays = localOverlays;
          config = {
            allowUnfree = true;
            nvidia.acceptLicense = true;
            permittedInsecurePackages = nixpkgs.lib.optionals isDarwin [
              "olm-3.2.16"
            ];
          };
        };

      mkHomeConfiguration =
        {
          arch,
          profile,
          username,
        }:
        home-manager.lib.homeManagerConfiguration {
          pkgs = mkPkgs arch;
          extraSpecialArgs = {
            inherit
              inputs
              username
              profile
              constants
              privateConfig
              self
              ;
          };
          modules = [
            inputs.nix-openclaw.homeManagerModules.openclaw
            inputs.hermes-agent.homeManagerModules.default
            inputs.sops-nix.homeManagerModules.sops
            ./home-manager/home.nix
          ];
        };
    in
    {
      homeConfigurations = {
        "${privateConfig.identity.username}" = mkHomeConfiguration {
          arch = constants.systems.linux.arch;
          profile = constants.profiles.desktop;
          username = privateConfig.identity.username;
        };
        "almalinux" = mkHomeConfiguration {
          arch = constants.systems.linux.arch;
          profile = constants.profiles.server;
          username = "almalinux";
        };
        "${privateConfig.work.username}" = mkHomeConfiguration {
          arch = constants.systems.darwin.arch;
          profile = constants.profiles.desktop;
          username = privateConfig.work.username;
        };
      };

      formatter = forAllSystems (
        arch:
        let
          pkgs = nixpkgs.legacyPackages.${arch};
        in
        (import ./checks/formatting.nix { inherit self pkgs; }).formatter
      );

      checks = forAllSystems (
        arch:
        let
          pkgs = nixpkgs.legacyPackages.${arch};
          baseChecks = import ./checks {
            inherit
              home-manager
              nixpkgs
              self
              pkgs
              ;
            inherit (inputs) sops-nix;
          };
          homeConfigChecks =
            if arch == "x86_64-linux" then
              {
                "home-${privateConfig.identity.username}" =
                  self.homeConfigurations.${privateConfig.identity.username}.activationPackage;
                home-almalinux = self.homeConfigurations.almalinux.activationPackage;
                prime-agent-runtime =
                  self.homeConfigurations.${privateConfig.identity.username}.config.modules.development.primeAgent.package.runtimePackage;
              }
            else if arch == "aarch64-darwin" then
              {
                "home-${privateConfig.work.username}" =
                  self.homeConfigurations.${privateConfig.work.username}.activationPackage;
                prime-agent-runtime =
                  self.homeConfigurations.${privateConfig.work.username}.config.modules.development.primeAgent.package.runtimePackage;
              }
            else
              { };
        in
        baseChecks // homeConfigChecks
      );
    };
}
