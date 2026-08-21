{
  config,
  inputs,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.development.hermesAgent;
  serviceCfg = config.services.hermes-agent;
  system = pkgs.stdenv.hostPlatform.system;
  isDarwin = pkgs.stdenv.hostPlatform.isDarwin;
  isLinux = pkgs.stdenv.hostPlatform.isLinux;
  configDir = serviceCfg.hermesHome;

  hermesInputs = inputs.hermes-agent.inputs // {
    self = inputs.hermes-agent;
  };
  hermesPackageModule = import "${inputs.hermes-agent}/nix/packages.nix" {
    inputs = hermesInputs;
  };
  hermesModuleCommon = import "${inputs.hermes-agent}/nix/moduleCommon.nix" {
    inherit lib;
  };
  hermesPackages = hermesPackageModule.perSystem {
    inherit lib pkgs;
    inputs' = {
      npm-lockfile-fix.packages.default =
        inputs.hermes-agent.inputs.npm-lockfile-fix.packages.${system}.default;
    };
  };
  baseHermesAgentPackage = hermesPackages.packages.default;

  cudaRuntimeEnabled = isLinux && config.modules.core.gpu.acceleration == "cuda";
  voiceRuntimeLibVar = if isDarwin then "DYLD_FALLBACK_LIBRARY_PATH" else "LD_LIBRARY_PATH";
  voiceRuntimeLibPath =
    lib.makeLibraryPath (
      [ pkgs.portaudio ]
      ++ lib.optionals cudaRuntimeEnabled [
        # CTranslate2 4.7.1 wheels dlopen libcublas.so.12 independently of the selected CUDA package set.
        pkgs.cudaPackages_12_9.libcublas
      ]
    )
    # They also dlopen libcuda.so.1, so expose addDriverRunpath.driverLink.
    + lib.optionalString cudaRuntimeEnabled ":${pkgs.addDriverRunpath.driverLink}/lib";

  # Keep the upstream package overridable: its Home Manager module applies
  # extra dependency groups after selecting services.hermes-agent.package.
  wrapHermesAgent =
    package:
    let
      wrapped = package.overrideAttrs (previousAttrs: {
        nativeBuildInputs = lib.unique ((previousAttrs.nativeBuildInputs or [ ]) ++ [ pkgs.makeWrapper ]);
        postFixup = (previousAttrs.postFixup or "") + ''
          for bin in "$out"/bin/*; do
            [ -x "$bin" ] || continue
            wrapProgram "$bin" --prefix ${voiceRuntimeLibVar} : "${voiceRuntimeLibPath}"
          done
        '';
      });
    in
    wrapped
    // {
      override =
        requested:
        wrapHermesAgent (
          package.override (
            previous:
            let
              overrides = if builtins.isFunction requested then requested previous else requested;
            in
            overrides
            // lib.optionalAttrs (overrides ? extraDependencyGroups) {
              # The upstream full package already carries portable integration
              # groups; additional groups must extend rather than replace them.
              extraDependencyGroups = lib.unique (
                (previous.extraDependencyGroups or [ ]) ++ overrides.extraDependencyGroups
              );
            }
          )
        );
    };

  hermesAgentPackage = wrapHermesAgent baseHermesAgentPackage;
  effectiveHermesAgentPackage = hermesModuleCommon.effectivePackage serviceCfg;
  hermesDesktopPackage = effectiveHermesAgentPackage.hermesDesktop or null;

  optionalPackages = config.modules.core.lib.mkOptionalPackages [
    {
      package = cfg.desktopPackage;
      enabled = cfg.enableDesktop;
      warning = "hermesAgent: desktopPackage not available for system ${system}";
    }
  ];
in
{
  options.modules.development.hermesAgent = {
    enable = lib.mkEnableOption "hermes-agent configuration";

    enableGateway = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Whether to run the Hermes Agent messaging gateway";
    };

    enableDashboard = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Whether to run the Hermes Agent web dashboard and desktop backend";
    };

    enableDesktop = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Whether to install the Hermes Agent desktop app";
    };

    desktopPackage = config.modules.core.lib.mkOptionalPackageOption {
      default = hermesDesktopPackage;
      defaultText = lib.literalExpression "hermesAgentPackage.hermesDesktop";
      description = "Hermes Agent desktop package";
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = serviceCfg.environment == { } && serviceCfg.environmentFiles == [ ];
        message = ''
          Hermes Agent environment variables are managed by the sops-nix
          hermes-env secret; leave services.hermes-agent.environment and
          services.hermes-agent.environmentFiles empty.
        '';
      }
    ];

    services.hermes-agent = {
      enable = true;
      package = lib.mkDefault hermesAgentPackage;
      gateway.enable = cfg.enableGateway;
      backend.mode = if cfg.enableDashboard then "dashboard" else "none";
    };

    home = {
      packages = optionalPackages.packages;

      # Keep .env linked to the current sops generation. The upstream module
      # copies environmentFiles before sops-nix refreshes them, which can
      # otherwise leave stale credentials until the next activation.
      activation.hermesAgentEnvironment = lib.hm.dag.entryAfter [ "hermesAgentSetup" "sops-nix" ] ''
        run mkdir -p "${configDir}"
        run ln -sfn "${config.sops.secrets."hermes-env".path}" "${configDir}/.env"
      '';
    };

    warnings = optionalPackages.warnings;
  };
}
