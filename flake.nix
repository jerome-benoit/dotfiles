{
  description = "Fraggle's nix flakes configuration";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs?ref=nixpkgs-unstable";
    home-manager.url = "github:nix-community/home-manager";
    home-manager.inputs.nixpkgs.follows = "nixpkgs";
    opencode.url = "github:anomalyco/opencode";
    opencode.inputs.nixpkgs.follows = "nixpkgs";
    opencode-nvim = {
      url = "github:NickvanDyke/opencode.nvim";
      flake = false;
    };
    agent-of-empires.url = "github:njbrake/agent-of-empires";
    agent-of-empires.inputs.nixpkgs.follows = "nixpkgs";
    agent-of-empires.inputs.flake-parts.follows = "flake-parts";
    agent-deck = {
      url = "github:asheshgoplani/agent-deck";
      flake = false;
    };
    agtx = {
      url = "github:fynnfluegge/agtx";
      flake = false;
    };
    openspec.url = "github:Fission-AI/OpenSpec";
    openspec.inputs.nixpkgs.follows = "nixpkgs";
    qmd.url = "github:tobi/qmd";
    qmd.inputs.nixpkgs.follows = "nixpkgs";
    qmd.inputs.flake-utils.follows = "flake-utils";
    nix-openclaw.url = "github:openclaw/nix-openclaw";
    nix-openclaw.inputs.nixpkgs.follows = "nixpkgs";
    nix-openclaw.inputs.home-manager.follows = "home-manager";
    nix-openclaw.inputs.flake-utils.follows = "flake-utils";
    nix-openclaw.inputs.nix-steipete-tools.follows = "nix-steipete-tools";
    flake-utils.url = "github:numtide/flake-utils";
    flake-parts.url = "github:hercules-ci/flake-parts";
    nix-steipete-tools.url = "github:openclaw/nix-steipete-tools";
    nix-steipete-tools.inputs.nixpkgs.follows = "nixpkgs";
    hermes-agent.url = "github:NousResearch/hermes-agent";
    hermes-agent.inputs.nixpkgs.follows = "nixpkgs";
    hermes-agent.inputs.flake-parts.follows = "flake-parts";
    hermes-agent.inputs.pyproject-build-systems.inputs.pyproject-nix.follows =
      "hermes-agent/pyproject-nix";
    hermes-agent.inputs.pyproject-build-systems.inputs.uv2nix.follows = "hermes-agent/uv2nix";
    hermes-agent.inputs.uv2nix.inputs.pyproject-nix.follows = "hermes-agent/pyproject-nix";
  };

  outputs =
    {
      self,
      nixpkgs,
      home-manager,
      opencode,
      opencode-nvim,
      agent-of-empires,
      agent-deck,
      agtx,
      openspec,
      qmd,
      flake-utils,
      flake-parts,
      nix-openclaw,
      nix-steipete-tools,
      hermes-agent,
    }@inputs:
    let
      constants = import ./constants.nix;
      forAllSystems = nixpkgs.lib.genAttrs (
        builtins.attrValues (nixpkgs.lib.mapAttrs (_: sys: sys.arch) constants.systems)
      );

      mkHomeConfiguration =
        {
          arch,
          username,
        }:
        home-manager.lib.homeManagerConfiguration {
          pkgs = nixpkgs.legacyPackages.${arch};
          extraSpecialArgs = {
            inherit
              inputs
              username
              constants
              self
              ;
          };
          modules = [
            inputs.nix-openclaw.homeManagerModules.openclaw
            ./home-manager/home.nix
          ];
        };
    in
    {
      homeConfigurations = {
        "fraggle" = mkHomeConfiguration {
          arch = constants.systems.linux.arch;
          username = "fraggle";
        };
        "almalinux" = mkHomeConfiguration {
          arch = constants.systems.linux.arch;
          username = "almalinux";
        };
        "I339261" = mkHomeConfiguration {
          arch = constants.systems.darwin.arch;
          username = "I339261";
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
              self
              pkgs
              ;
          };
          homeConfigChecks =
            if arch == "x86_64-linux" then
              {
                home-fraggle = self.homeConfigurations.fraggle.activationPackage;
                home-almalinux = self.homeConfigurations.almalinux.activationPackage;
              }
            else if arch == "aarch64-darwin" then
              {
                home-I339261 = self.homeConfigurations.I339261.activationPackage;
              }
            else
              { };
        in
        baseChecks // homeConfigChecks
      );
    };
}
