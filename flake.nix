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

      # Force LLD on darwin; cctools ld64 hardening SIGTRAPs at link (NixOS/nixpkgs#540054).
      forceLld =
        prev: drv:
        drv.overrideAttrs (previousAttrs: {
          nativeBuildInputs = (previousAttrs.nativeBuildInputs or [ ]) ++ [ prev.llvmPackages.lld ];
          NIX_CFLAGS_LINK = (previousAttrs.NIX_CFLAGS_LINK or "") + " -fuse-ld=lld";
        });

      localOverlays = [
        inputs.nix-openclaw.overlays.default
        (
          final: prev:
          nixpkgs.lib.optionalAttrs prev.stdenv.hostPlatform.isDarwin {
            whisper-cpp = forceLld prev prev.whisper-cpp;
            qt6Packages = prev.qt6Packages.overrideScope (
              _: qprev: {
                qtkeychain = forceLld prev qprev.qtkeychain;
              }
            );
            nheko = forceLld prev (prev.nheko.override { inherit (final) qt6Packages; });
            # agent tests break on hardcoded /tmp/crush-test in darwin's shared /tmp.
            crush = prev.crush.overrideAttrs (previousAttrs: {
              postPatch = (previousAttrs.postPatch or "") + ''
                substituteInPlace internal/agent/common_test.go \
                  --replace-fail '"/tmp/crush-test/"' 'os.TempDir()'
              '';
            });
            # vscode ripgrep moved to node_modules.asar.unpacked (NixOS/nixpkgs#543825).
            vscode = prev.vscode.overrideAttrs (previousAttrs: {
              postPatch =
                nixpkgs.lib.replaceStrings
                  [ "Contents/Resources/app/node_modules/@vscode/ripgrep-universal" ]
                  [ "Contents/Resources/app/node_modules.asar.unpacked/@vscode/ripgrep-universal" ]
                  (previousAttrs.postPatch or "");
            });
          }
        )
        (_: prev: {
          pythonPackagesExtensions = prev.pythonPackagesExtensions ++ [
            (
              _: pyprev:
              (nixpkgs.lib.optionalAttrs prev.stdenv.hostPlatform.isDarwin {
                # retry/timeout tests break on wall-clock timing asserts on the darwin builder.
                opentelemetry-exporter-otlp-proto-grpc =
                  pyprev.opentelemetry-exporter-otlp-proto-grpc.overrideAttrs
                    (previousAttrs: {
                      disabledTests = (previousAttrs.disabledTests or [ ]) ++ [
                        "test_retry_info_is_respected"
                        "test_timeout_set_correctly"
                      ];
                    });
              })
              // {
                # langfuse 4.0.2 caps wrapt below 2, but its import check passes with wrapt 2.
                langfuse = pyprev.langfuse.overridePythonAttrs (previousAttrs: {
                  pythonRelaxDeps = (previousAttrs.pythonRelaxDeps or [ ]) ++ [ "wrapt" ];
                });
              }
            )
          ];
        })
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
              }
            else if arch == "aarch64-darwin" then
              {
                "home-${privateConfig.work.username}" =
                  self.homeConfigurations.${privateConfig.work.username}.activationPackage;
              }
            else
              { };
        in
        baseChecks // homeConfigChecks
      );
    };
}
