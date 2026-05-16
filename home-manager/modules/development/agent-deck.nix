{
  config,
  lib,
  pkgs,
  inputs,
  ...
}:

let
  cfg = config.modules.development.agent-deck;
  constants = config.modules.core.constants;

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
        user_id = ${constants.identity.telegram.userId}
      [conductor.slack]
        bot_token = ""
        app_token = ""
        channel_id = ""
        listen_mode = ""

    [tmux]
  '';

  agentDeckPackage = pkgs.buildGoModule (finalAttrs: {
    pname = "agent-deck";
    version = config.modules.core.lib.mkUnstableVersion inputs.agent-deck;
    src = inputs.agent-deck;

    vendorHash = "sha256-/7hzCID4Vu9z6VHN7NiAjyoZPEBPHet4fJdh/VSZaGQ=";
    subPackages = [ "cmd/agent-deck" ];

    ldflags = [
      "-s"
      "-w"
      "-X main.Version=${finalAttrs.version}"
    ];

    doCheck = false;

    meta = {
      description = "Terminal session manager for AI coding agents";
      longDescription = ''
        Agent Deck is a command center for AI coding agents. One terminal,
        all your agents, complete visibility. Supports Claude Code, Gemini CLI,
        OpenCode, Codex, and custom tools.

        Features include session forking, MCP manager, status detection,
        git worktrees, conductor orchestration, and notification bar.
      '';
      homepage = "https://github.com/asheshgoplani/agent-deck";
      license = lib.licenses.mit;
      platforms = lib.platforms.unix;
      mainProgram = "agent-deck";
    };
  });
in
{
  options.modules.development.agent-deck = {
    enable = lib.mkEnableOption "agent-deck configuration";

    package = lib.mkOption {
      type = lib.types.package;
      default = agentDeckPackage;
      defaultText = lib.literalExpression "inputs.agent-deck built with buildGoModule";
      description = "Agent Deck package";
      example = lib.literalExpression "pkgs.agent-deck";
    };

    defaultTool = lib.mkOption {
      type = lib.types.enum [
        "claude"
        "gemini"
        "opencode"
        "codex"
        "pi"
      ];
      default = "opencode";
      description = "Default AI tool for new sessions";
      example = "claude";
    };

    theme = lib.mkOption {
      type = lib.types.enum [
        "dark"
        "light"
        "system"
      ];
      default = "system";
      description = "Color scheme: dark, light, or system";
      example = "dark";
    };
  };

  config = lib.mkIf cfg.enable {
    home.packages = [ cfg.package ];

    home.activation.agentDeckConfig =
      let
        configDir = "${config.home.homeDirectory}/.agent-deck";
        configFile = "${configDir}/config.toml";
      in
      lib.hm.dag.entryAfter [ "writeBoundary" "sops-nix" ] ''
        run mkdir -p "${configDir}"
        if [[ ! -f "${configFile}" ]]; then
          run cat > "${configFile}" << 'EOF'
        ${agentDeckConfig}
        EOF
          run chmod 600 "${configFile}"
        fi
        export TELEGRAM_TOKEN=$(cat "${
          config.sops.secrets."agentdeck-telegram-token".path
        }" 2>/dev/null | tr -d '\n' || true)
        export SLACK_BOT_TOKEN=$(cat "${
          config.sops.secrets."agentdeck-slack-bot-token".path
        }" 2>/dev/null | tr -d '\n' || true)
        export SLACK_APP_TOKEN=$(cat "${
          config.sops.secrets."agentdeck-slack-app-token".path
        }" 2>/dev/null | tr -d '\n' || true)

        if [[ -z "$TELEGRAM_TOKEN" && -z "$SLACK_BOT_TOKEN" && -z "$SLACK_APP_TOKEN" ]]; then
          echo "sops: conductor tokens unavailable — skipping injection" >&2
        elif [[ -f "${configFile}" ]]; then
          # flip-flop + eof: scope substitution to each TOML section
          ${lib.getExe pkgs.perl} -pi -e '
            sub toml_escape { my $v = shift; my %m = ("\\"=>"\\\\", "\""=>"\\\"", "\n"=>"\\n", "\r"=>"\\r", "\t"=>"\\t", "\x08"=>"\\b", "\x0c"=>"\\f"); $v =~ s/([\\\"\n\r\t\x08\x0c])/$m{$1}/g; return $v; }
            if (/^\s*\[conductor\.telegram\]/ .. (eof() || /^\s*\[(?!conductor\.telegram)/)) {
              s/^(\s*token\s*=\s*).*/$1"@{[toml_escape($ENV{TELEGRAM_TOKEN})]}"/ if $ENV{TELEGRAM_TOKEN} ne "";
            }
            if (/^\s*\[conductor\.slack\]/ .. (eof() || /^\s*\[(?!conductor\.slack)/)) {
              s/^(\s*bot_token\s*=\s*).*/$1"@{[toml_escape($ENV{SLACK_BOT_TOKEN})]}"/ if $ENV{SLACK_BOT_TOKEN} ne "";
              s/^(\s*app_token\s*=\s*).*/$1"@{[toml_escape($ENV{SLACK_APP_TOKEN})]}"/ if $ENV{SLACK_APP_TOKEN} ne "";
            }
          ' "${configFile}"
          if [[ -n "$TELEGRAM_TOKEN" ]] && ! grep -q '^\s*\[conductor\.telegram\]' "${configFile}"; then
            echo "warning: TELEGRAM_TOKEN set but [conductor.telegram] section missing in config" >&2
          fi
          if [[ -n "$SLACK_BOT_TOKEN" || -n "$SLACK_APP_TOKEN" ]] && ! grep -q '^\s*\[conductor\.slack\]' "${configFile}"; then
            echo "warning: Slack tokens set but [conductor.slack] section missing in config" >&2
          fi
        fi
        unset TELEGRAM_TOKEN SLACK_BOT_TOKEN SLACK_APP_TOKEN
      '';
  };
}
