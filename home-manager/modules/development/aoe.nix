{
  config,
  lib,
  pkgs,
  inputs,
  ...
}:

let
  cfg = config.modules.development.aoe;
  system = pkgs.stdenv.hostPlatform.system;

  aoePackages = inputs.agent-of-empires.packages.${system} or { };
  baseAoePackage =
    if cfg.enableWeb then aoePackages.aoe-with-web or null else aoePackages.default or null;
  # Workaround: Nixpkgs installs Cursor as cursor-agent, not the generic agent.
  # Remove when upstream's registry detects and launches cursor-agent.
  aoePackage =
    if baseAoePackage == null then
      null
    else
      baseAoePackage.overrideAttrs (old: {
        patches = (old.patches or [ ]) ++ [ ../../../patches/agent-of-empires-cursor-executable.patch ];
        env = (old.env or { }) // {
          NIX_AOE_WHICH = "${pkgs.which}/bin/which";
        };
      });

  aoeConfig = ''
    [theme]
    name = "${cfg.theme}"

    [session]
    default_tool = "${cfg.defaultTool}"
  '';

  optionalPackages = config.modules.core.lib.mkOptionalPackages [
    {
      package = cfg.package;
      warning = "aoe: package not available for system ${system}";
    }
  ];
in
{
  options.modules.development.aoe = {
    enable = lib.mkEnableOption "agent-of-empires (aoe) configuration";

    enableWeb = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Whether to build with embedded web dashboard (aoe-with-web)";
    };

    package = config.modules.core.lib.mkOptionalPackageOption {
      default = aoePackage;
      defaultText = lib.literalExpression "inputs.agent-of-empires.packages.\${system}.default or .aoe-with-web";
      description = "Agent of Empires package";
      example = lib.literalExpression "inputs.agent-of-empires.packages.\${system}.default";
    };

    theme = lib.mkOption {
      type = lib.types.enum [
        "phosphor"
        "tokyo-night-storm"
        "catppuccin-latte"
        "dracula"
        "empire"
        "rose-pine"
      ];
      default = "tokyo-night-storm";
      description = "TUI theme";
    };

    defaultTool = lib.mkOption {
      type = lib.types.nullOr (
        lib.types.enum [
          "claude"
          "opencode"
          "vibe"
          "codex"
          "gemini"
          "cursor"
          "copilot"
          "pi"
          "droid"
          "settl"
          "hermes"
          "kiro"
          "qwen"
        ]
      );
      default = "opencode";
      description = "Default AI agent for new sessions";
    };
  };

  config = lib.mkIf cfg.enable {
    home.packages = optionalPackages.packages;

    warnings = optionalPackages.warnings;

    home.activation.aoeConfig = lib.mkIf (cfg.package != null && cfg.defaultTool != null) (
      lib.hm.dag.entryAfter [ "writeBoundary" ] ''
        (
          aoeHome=${lib.escapeShellArg config.home.homeDirectory}
          # Activation may still inherit the previous session's XDG environment.
          ${config.lib.shell.exportAll (
            lib.optionalAttrs (config.home.sessionVariables ? XDG_CONFIG_HOME) {
              inherit (config.home.sessionVariables) XDG_CONFIG_HOME;
            }
          )}
          # Without a declared export, match upstream's environment lookup.
          if [[ "''${XDG_CONFIG_HOME-}" == /* ]]; then
            aoeXdgBase=$XDG_CONFIG_HOME
          else
            aoeXdgBase="$aoeHome/.config"
          fi
          aoeConfigDir="$aoeXdgBase/agent-of-empires"
          ${lib.optionalString pkgs.stdenv.hostPlatform.isDarwin ''
            # Resolve existing layouts during activation, without moving user data.
            aoeLegacyDir="$aoeHome/.agent-of-empires"
            if [[ ! -e "$aoeConfigDir" ]]; then
              if [[ -e "$aoeLegacyDir" || "''${XDG_CONFIG_HOME-}" != /* ]]; then
                aoeConfigDir=$aoeLegacyDir
              fi
            fi
          ''}
          aoeConfigFile="$aoeConfigDir/config.toml"
          run mkdir -p -- "$aoeConfigDir"
          if [[ ! -e "$aoeConfigFile" && ! -L "$aoeConfigFile" ]]; then
            run ${lib.getExe pkgs.bash} -c 'cat > "$1"' -- "$aoeConfigFile" << 'EOF'
        ${aoeConfig}
        EOF
          fi
        )
      ''
    );
  };
}
