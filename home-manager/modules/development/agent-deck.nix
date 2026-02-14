{
  config,
  lib,
  pkgs,
  inputs,
  ...
}:

let
  cfg = config.modules.development.agent-deck;

  agentDeckPackage = pkgs.buildGoModule {
    pname = "agent-deck";
    version = "unstable-${inputs.agent-deck.shortRev}";
    src = inputs.agent-deck;

    vendorHash = "sha256-k0jRlsFmBJNbfX3u2UQlnx/Z25KII8fYegU+Z77/EO0=";
    subPackages = [ "cmd/agent-deck" ];

    ldflags = [
      "-s"
      "-w"
      "-X main.Version=unstable-${inputs.agent-deck.shortRev}"
    ];

    doCheck = false;
    nativeBuildInputs = [ pkgs.installShellFiles ];

    postInstall = lib.optionalString (pkgs.stdenv.buildPlatform.canExecute pkgs.stdenv.hostPlatform) ''
      installShellCompletion --cmd agent-deck \
        --bash <($out/bin/agent-deck completion bash 2>/dev/null || true) \
        --fish <($out/bin/agent-deck completion fish 2>/dev/null || true) \
        --zsh <($out/bin/agent-deck completion zsh 2>/dev/null || true)
    '';

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
  };

  config = lib.mkIf cfg.enable {
    home.packages = [ cfg.package ];
  };
}
