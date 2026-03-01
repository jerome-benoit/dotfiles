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

  aoeConfig = ''
    [theme]
    name = "${cfg.theme}"

    [session]
    default_tool = "${cfg.defaultTool}"
  '';
in
{
  options.modules.development.aoe = {
    enable = lib.mkEnableOption "agent-of-empires (aoe) configuration";

    package = lib.mkOption {
      type = lib.types.nullOr lib.types.package;
      default = inputs.agent-of-empires.packages.${system}.default or null;
      defaultText = lib.literalExpression "inputs.agent-of-empires.packages.\${system}.default";
      description = "Agent of Empires package";
      example = lib.literalExpression "inputs.agent-of-empires.packages.\${system}.default";
    };

    theme = lib.mkOption {
      type = lib.types.enum [
        "phosphor"
        "tokyo-night-storm"
        "catppuccin-latte"
        "dracula"
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
        ]
      );
      default = "opencode";
      description = "Default AI agent for new sessions";
    };
  };

  config = lib.mkIf cfg.enable {
    home.packages = lib.optional (cfg.package != null) cfg.package;

    warnings = lib.optional (cfg.package == null) "aoe: package not available for system ${system}";

    home.activation.aoeConfig = lib.mkIf (cfg.package != null && cfg.defaultTool != null) (
      let
        configDir =
          if pkgs.stdenv.isDarwin then
            "${config.home.homeDirectory}/.agent-of-empires"
          else
            "${config.xdg.configHome}/agent-of-empires";
        configFile = "${configDir}/config.toml";
      in
      lib.hm.dag.entryAfter [ "writeBoundary" ] ''
        run mkdir -p "${configDir}"
        if [[ ! -f "${configFile}" ]]; then
          run cat > "${configFile}" << 'EOF'
        ${aoeConfig}
        EOF
        fi
      ''
    );
  };
}
