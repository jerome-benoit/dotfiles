{
  description = "Fraggle's nix flakes configuration";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs?ref=nixpkgs-unstable";
    home-manager.url = "github:nix-community/home-manager";
    home-manager.inputs.nixpkgs.follows = "nixpkgs";
    sops-nix.url = "github:Mic92/sops-nix";
    sops-nix.inputs.nixpkgs.follows = "nixpkgs";
    opencode.url = "github:anomalyco/opencode";
    opencode.inputs.nixpkgs.follows = "nixpkgs";
    opencode-nvim = {
      url = "github:NickvanDyke/opencode.nvim";
      flake = false;
    };
    agent-of-empires.url = "git+ssh://git@github.com/agent-of-empires/agent-of-empires";
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
    nix-openclaw.inputs.nix-openclaw-tools.follows = "nix-openclaw-tools";
    nix-openclaw.inputs.qmd.follows = "qmd";
    flake-utils.url = "github:numtide/flake-utils";
    flake-parts.url = "github:hercules-ci/flake-parts";
    nix-openclaw-tools.url = "github:openclaw/nix-openclaw-tools";
    nix-openclaw-tools.inputs.nixpkgs.follows = "nixpkgs";
    # See .serena/memories/processes/hermes_agent_sync_main_patched.md
    hermes-agent.url = "github:jerome-benoit/hermes-agent/main-patched";
    hermes-agent.inputs.nixpkgs.follows = "nixpkgs";
    hermes-agent.inputs.flake-parts.follows = "flake-parts";
    hermes-agent.inputs.pyproject-nix.follows = "pyproject-nix";
    hermes-agent.inputs.uv2nix.follows = "uv2nix";
    hermes-agent.inputs.pyproject-build-systems.follows = "pyproject-build-systems";
    pyproject-nix.url = "github:pyproject-nix/pyproject.nix";
    pyproject-nix.inputs.nixpkgs.follows = "nixpkgs";
    uv2nix.url = "github:pyproject-nix/uv2nix";
    uv2nix.inputs.nixpkgs.follows = "nixpkgs";
    uv2nix.inputs.pyproject-nix.follows = "pyproject-nix";
    pyproject-build-systems.url = "github:pyproject-nix/build-system-pkgs";
    pyproject-build-systems.inputs.nixpkgs.follows = "nixpkgs";
    pyproject-build-systems.inputs.pyproject-nix.follows = "pyproject-nix";
    pyproject-build-systems.inputs.uv2nix.follows = "uv2nix";
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
      personalSecrets = import ./secrets/default.nix;
      forAllSystems = nixpkgs.lib.genAttrs (
        builtins.attrValues (nixpkgs.lib.mapAttrs (_: sys: sys.arch) constants.systems)
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
          }
        )
        (_: prev: {
          pythonPackagesExtensions = prev.pythonPackagesExtensions ++ [
            (
              _: pyprev:
              nixpkgs.lib.optionalAttrs prev.stdenv.hostPlatform.isDarwin {
                # retry/timeout tests break on wall-clock timing asserts on the darwin builder.
                opentelemetry-exporter-otlp-proto-grpc =
                  pyprev.opentelemetry-exporter-otlp-proto-grpc.overrideAttrs
                    (previousAttrs: {
                      disabledTests = (previousAttrs.disabledTests or [ ]) ++ [
                        "test_retry_info_is_respected"
                        "test_timeout_set_correctly"
                      ];
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
          username,
        }:
        home-manager.lib.homeManagerConfiguration {
          pkgs = mkPkgs arch;
          extraSpecialArgs = {
            inherit
              inputs
              username
              constants
              personalSecrets
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
        "${personalSecrets.identity.username}" = mkHomeConfiguration {
          arch = constants.systems.linux.arch;
          username = personalSecrets.identity.username;
        };
        "almalinux" = mkHomeConfiguration {
          arch = constants.systems.linux.arch;
          username = "almalinux";
        };
        "${personalSecrets.work.username}" = mkHomeConfiguration {
          arch = constants.systems.darwin.arch;
          username = personalSecrets.work.username;
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
                "home-${personalSecrets.identity.username}" =
                  self.homeConfigurations.${personalSecrets.identity.username}.activationPackage;
                home-almalinux = self.homeConfigurations.almalinux.activationPackage;
              }
            else if arch == "aarch64-darwin" then
              {
                "home-${personalSecrets.work.username}" =
                  self.homeConfigurations.${personalSecrets.work.username}.activationPackage;
              }
            else
              { };
        in
        baseChecks // homeConfigChecks
      );
    };
}
