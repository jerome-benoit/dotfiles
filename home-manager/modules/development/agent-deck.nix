{
  config,
  lib,
  pkgs,
  inputs,
  ...
}:

let
  cfg = config.modules.development.agent-deck;

  agentDeckConfig = ''
    # Agent Deck Configuration
    # Edit this file or use Settings (press S) in the TUI

    default_tool = "${cfg.defaultTool}"
    theme = "${cfg.theme}"
    mcp_default_scope = ""

    [tools]

    [mcps]

    [claude]
      command = ""
      config_dir = ""
      dangerous_mode = false
      allow_dangerous_mode = false
      env_file = ""

    [gemini]
      yolo_mode = false
      default_model = ""
      env_file = ""

    [opencode]
      default_model = ""
      default_agent = ""
      env_file = ""

    [codex]
      yolo_mode = false

    [worktree]
      auto_cleanup = false
      default_location = ""

    [global_search]
      enabled = true
      tier = "auto"
      memory_limit_mb = 0
      recent_days = 90
      index_rate_limit = 0

    [logs]
      max_size_mb = 10
      max_lines = 10000
      remove_orphans = true
      debug_level = ""
      debug_format = ""
      debug_max_mb = 0
      debug_backups = 0
      debug_retention_days = 0
      debug_compress = false
      ring_buffer_mb = 0
      pprof_enabled = false
      aggregate_interval_secs = 0

    [mcp_pool]
      enabled = false
      auto_start = false
      port_start = 0
      port_end = 0
      start_on_demand = false
      shutdown_on_exit = false
      fallback_to_stdio = true
      show_pool_status = false
      pool_all = false
      socket_wait_timeout = 0

    [updates]
      auto_update = false
      check_enabled = true
      check_interval_hours = 0
      notify_in_cli = false

    [preview]
      show_output = true
      show_analytics = false
      [preview.analytics]

    [experiments]
      directory = ""
      date_prefix = false
      default_tool = ""

    [notifications]
      enabled = false
      max_shown = 0

    [instances]

    [shell]
      init_script = ""

    [maintenance]
      enabled = false

    [status]

    [conductor]
      enabled = false
      heartbeat_interval = 0
      [conductor.telegram]
        token = ""
        user_id = 0
      [conductor.slack]
        bot_token = ""
        app_token = ""
        channel_id = ""
        listen_mode = ""

    [tmux]
  '';

  agentDeckPackage = pkgs.buildGoModule {
    pname = "agent-deck";
    version = "unstable-${inputs.agent-deck.shortRev}";
    src = inputs.agent-deck;

    vendorHash = "sha256-hoVn3RTKhp0e48dPZlUQIPQygXA9Fi6hnJruaS53srQ=";
    subPackages = [ "cmd/agent-deck" ];

    ldflags = [
      "-s"
      "-w"
      "-X main.Version=unstable-${inputs.agent-deck.shortRev}"
    ];

    doCheck = false;

    meta = with lib; {
      description = "Terminal session manager for AI coding agents";
      longDescription = ''
        Agent Deck is a command center for AI coding agents. One terminal,
        all your agents, complete visibility. Supports Claude Code, Gemini CLI,
        OpenCode, Codex, and custom tools.

        Features include session forking, MCP manager, status detection,
        git worktrees, conductor orchestration, and notification bar.
      '';
      homepage = "https://github.com/asheshgoplani/agent-deck";
      license = licenses.mit;
      maintainers = [ ];
      platforms = platforms.unix;
      mainProgram = "agent-deck";
    };
  };
in
{
  options.modules.development.agent-deck = {
    enable = lib.mkEnableOption "agent-deck configuration";

    package = lib.mkOption {
      type = lib.types.package;
      default = agentDeckPackage;
      defaultText = lib.literalExpression "inputs.agent-deck built with buildGoModule";
      description = "Agent Deck package";
    };

    defaultTool = lib.mkOption {
      type = lib.types.nullOr (
        lib.types.enum [
          "claude"
          "gemini"
          "opencode"
          "codex"
        ]
      );
      default = "opencode";
      description = "Default AI tool for new sessions";
    };

    theme = lib.mkOption {
      type = lib.types.nullOr (
        lib.types.enum [
          "dark"
          "light"
          "system"
        ]
      );
      default = "system";
      description = "Color scheme: dark, light, or system";
    };
  };

  config = lib.mkIf cfg.enable {
    home.packages = [ cfg.package ];

    home.activation.agentDeckConfig =
      let
        configDir = "${config.home.homeDirectory}/.agent-deck";
        configFile = "${configDir}/config.toml";
      in
      lib.hm.dag.entryAfter [ "writeBoundary" ] ''
        run mkdir -p "${configDir}"
        if [[ ! -f "${configFile}" ]]; then
          run cat > "${configFile}" << 'EOF'
        ${agentDeckConfig}
        EOF
        fi
      '';
  };
}
