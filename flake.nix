{
  description = "Fraggle's nix flakes configuration";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs?ref=nixpkgs-unstable";
    home-manager.url = "github:nix-community/home-manager";
    home-manager.inputs.nixpkgs.follows = "nixpkgs";
    opencode.url = "github:sst/opencode";
    opencode-nvim = {
      url = "github:NickvanDyke/opencode.nvim";
      flake = false;
    };
  };

  outputs =
    {
      self,
      nixpkgs,
      home-manager,
      opencode,
      opencode-nvim,
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
            inherit inputs username constants;
          };
          modules = [ ./home-manager/home.nix ];
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
        in
        import ./checks {
          inherit
            self
            pkgs
            home-manager
            arch
            ;
        }
      );
    };
}
