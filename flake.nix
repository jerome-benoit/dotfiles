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
      systems = {
        linux = "x86_64-linux";
        darwin = "aarch64-darwin";
      };
      forAllSystems = nixpkgs.lib.genAttrs (builtins.attrValues systems);

      mkHomeConfiguration =
        {
          system,
          username,
        }:
        home-manager.lib.homeManagerConfiguration {
          pkgs = nixpkgs.legacyPackages.${system};
          extraSpecialArgs = {
            inherit inputs username;
          };
          modules = [ ./home-manager/home.nix ];
        };
    in
    {
      homeConfigurations = {
        "fraggle" = mkHomeConfiguration {
          system = systems.linux;
          username = "fraggle";
        };
        "I339261" = mkHomeConfiguration {
          system = systems.darwin;
          username = "I339261";
        };
      };

      formatter = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
        in
        pkgs.writeShellScriptBin "nix-fmt" ''
          set -euo pipefail
          [[ $# -eq 0 ]] && set -- .

          format_dir() {
            find "$1" -name '*.nix' -type f -exec ${pkgs.nixfmt-rfc-style}/bin/nixfmt {} +
          }

          for arg in "$@"; do
            [[ -d "$arg" ]] && format_dir "$arg" && continue
            [[ -f "$arg" ]] && ${pkgs.nixfmt-rfc-style}/bin/nixfmt "$arg" && continue
            echo "Error: $arg not found" >&2 && exit 1
          done
        ''
      );

      checks = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
        in
        {
          formatting =
            pkgs.runCommand "check-nix-formatting" { nativeBuildInputs = [ pkgs.nixfmt-rfc-style ]; }
              ''
                cd ${self}
                files=$(${pkgs.git}/bin/git ls-files '*.nix' 2>/dev/null || find . -name '*.nix' -type f)
                for file in $files; do
                  [ -f "$file" ] && ${pkgs.nixfmt-rfc-style}/bin/nixfmt --check "$file" || {
                    echo "ERROR: $file not formatted. Run 'nix fmt'" >&2
                    exit 1
                  }
                done
                echo "OK" > $out
              '';
        }
      );
    };
}
