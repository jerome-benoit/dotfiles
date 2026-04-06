{
  config,
  lib,
  pkgs,
  self,
  ...
}:

let
  cfg = config.modules.development.openclaw;
  constants = config.modules.core.constants;
  homeDir = config.home.homeDirectory;
  isDarwin = pkgs.stdenv.hostPlatform.isDarwin;

  openclawPackage = pkgs.openclaw.overrideAttrs (oldAttrs: {
    patches = (oldAttrs.patches or [ ]) ++ [
      # https://github.com/openclaw/openclaw/pull/59935
      (self + "/patches/openclaw/nix-home-manager-path-support.patch")
    ];
  });
in
{
  options.modules.development.openclaw = {
    enable = lib.mkEnableOption "OpenClaw AI gateway";
  };

  config = lib.mkIf cfg.enable {
    programs.openclaw = {
      enable = true;
      package = openclawPackage;
      stateDir = "${homeDir}/.openclaw";
      workspaceDir = "${homeDir}/.openclaw/workspace";
      installApp = isDarwin;
      exposePluginPackages = false;

      bundledPlugins = {
        summarize.enable = true;
        sag.enable = true;
        camsnap.enable = true;
        gogcli.enable = true;
        goplaces.enable = true;
        sonoscli.enable = true;
        peekaboo.enable = isDarwin;
        poltergeist.enable = isDarwin;
        # https://github.com/openclaw/nix-steipete-tools/issues/6
        bird.enable = false;
        imsg.enable = isDarwin;
      };

      launchd.enable = isDarwin;
      systemd.enable = !isDarwin;

      # Workaround: upstream synthetic defaultInstance omits appDefaults.nixMode
      instances.default = { };

      config = {
        gateway = {
          mode = "local";
          bind = "loopback";
          auth = {
            mode = "token";
            token = {
              source = "file";
              provider = "filemain";
              id = "/gateway/auth/token";
            };
          };
        };

        secrets = {
          providers.filemain = {
            source = "file";
            path = "~/.openclaw/secrets/openclaw-secrets.json";
            mode = "json";
          };
          defaults.file = "filemain";
        };

        auth.profiles."github-copilot:github" = {
          provider = "github-copilot";
          mode = "token";
        };

        channels.telegram = {
          enabled = true;
          dmPolicy = "allowlist";
          tokenFile = "~/.openclaw/secrets/telegram-bot-token";
          allowFrom = [ constants.telegramUserId ];
          groupPolicy = "disabled";
          configWrites = false;
          execApprovals = {
            enabled = true;
            approvers = [ constants.telegramUserId ];
            target = "dm";
          };
        };

        agents.defaults = {
          model = {
            primary = "github-copilot/gpt-5.4";
            fallbacks = [ "github-copilot/claude-opus-4.6" ];
          };
          models = {
            "github-copilot/gpt-5.4".alias = "GPT";
            "github-copilot/claude-opus-4.6".alias = "Opus";
            "github-copilot/claude-sonnet-4.6".alias = "Sonnet";
          };
          thinkingDefault = "high";
          maxConcurrent = 4;
          compaction.mode = "safeguard";
          subagents.maxConcurrent = 8;
        };

        plugins.entries = {
          telegram.enabled = true;
          github-copilot.enabled = true;
          memory-core.config.dreaming.enabled = true;
        };

        env.shellEnv.enabled = true;
        update.channel = "stable";

        tools.exec = {
          security = "allowlist";
          ask = "on-miss";
          strictInlineEval = true;
          safeBins = [
            "cut"
            "sort"
            "uniq"
            "head"
            "tail"
            "tr"
            "wc"
          ];
          safeBinTrustedDirs = [
            "/bin"
            "/usr/bin"
            "~/.nix-profile/bin"
          ]
          ++ lib.optionals isDarwin [ "/opt/homebrew/bin" ];
        };

        hooks.internal = {
          enabled = true;
          entries = {
            boot-md.enabled = true;
            command-logger.enabled = true;
            session-memory.enabled = true;
          };
        };

        messages.ackReactionScope = "group-mentions";

        commands = {
          native = "auto";
          nativeSkills = "auto";
        };
      };
    };

    # Generate active config with $include from the HM-managed symlink.
    # Writes to a separate file to preserve the HM symlink intact.
    home.activation.openclawLocalConfig =
      let
        jq = lib.getExe pkgs.jq;
        generateActiveConfig = pkgs.writeShellScript "openclaw-generate-active" ''
          set -e
          src="$1"
          dst="$2"
          if [ -L "$src" ]; then
            store_path="$(readlink "$src")"
          elif [ -f "$src" ]; then
            store_path="$src"
          else
            exit 1
          fi
          ${jq} '. + {"$include": ["./openclaw.local.json"]}' "$store_path" > "$dst.tmp"
          mv "$dst.tmp" "$dst"
        '';
        seedLocal = pkgs.writeShellScript "openclaw-seed-local" ''
          set -e
          mkdir -p "$(dirname "$1")"
          printf '{}\n' > "$1"
        '';
      in
      lib.hm.dag.entryAfter [ "openclawConfigFiles" ] ''
        LOCAL="${homeDir}/.openclaw/openclaw.local.json"
        if [[ ! -f "$LOCAL" ]]; then
          run ${seedLocal} "$LOCAL"
        fi

        CONFIG="${homeDir}/.openclaw/openclaw.json"
        ACTIVE="${homeDir}/.openclaw/openclaw.active.json"
        if [ -e "$CONFIG" ]; then
          run ${generateActiveConfig} "$CONFIG" "$ACTIVE"
        else
          warnEcho "openclaw: $CONFIG not found — openclawConfigFiles may not have run"
        fi
      '';

    # Point openclaw at the active config instead of the HM symlink
    home.sessionVariables.OPENCLAW_CONFIG_PATH = "${homeDir}/.openclaw/openclaw.active.json";
  };
}
