{
  config,
  lib,
  pkgs,
  inputs,
  ...
}:

let
  cfg = config.modules.development.aoe;

  aoeConfig = ''
    [session]
    default_tool = "${cfg.defaultTool}"
  '';

  aoePackage = pkgs.rustPlatform.buildRustPackage {
    pname = "aoe";
    version = "unstable-${inputs.agent-of-empires.shortRev}";
    src = inputs.agent-of-empires;

    cargoLock.lockFile = ./aoe-Cargo.lock;
    postPatch = "cp ${./aoe-Cargo.lock} Cargo.lock";

    nativeBuildInputs = with pkgs; [
      pkg-config
      perl
    ];

    buildInputs = [ ];

    doCheck = false;

    meta = with lib; {
      description = "Terminal session manager for AI coding agents";
      longDescription = ''
        Agent of Empires (AoE) is a terminal session manager for AI coding agents
        on Linux and macOS. Built on tmux, it allows running multiple AI agents
        in parallel across different branches of your codebase, each in its own
        isolated session with optional Docker sandboxing.

        Supports Claude Code, OpenCode, Mistral Vibe, Codex CLI, and Gemini CLI.
      '';
      homepage = "https://github.com/njbrake/agent-of-empires";
      license = licenses.mit;
      maintainers = [ ];
      platforms = platforms.unix;
      mainProgram = "aoe";
    };
  };
in
{
  options.modules.development.aoe = {
    enable = lib.mkEnableOption "agent-of-empires (aoe) configuration";

    package = lib.mkOption {
      type = lib.types.package;
      default = aoePackage;
      defaultText = lib.literalExpression "inputs.agent-of-empires built with rustPlatform";
      description = "Agent of Empires package";
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
    home.packages = [ cfg.package ];

    home.file.".agent-of-empires/config.toml" =
      lib.mkIf (pkgs.stdenv.isDarwin && cfg.defaultTool != null)
        {
          text = aoeConfig;
        };

    xdg.configFile."agent-of-empires/config.toml" =
      lib.mkIf (pkgs.stdenv.isLinux && cfg.defaultTool != null)
        {
          text = aoeConfig;
        };
  };
}
