{
  config,
  ...
}:

let
  homeDir = config.home.homeDirectory;
in
{
  sops.gnupg.home = "${homeDir}/.gnupg";
  sops.gnupg.sshKeyPaths = [];

  sops.defaultSopsFile = ../../../secrets/tokens.enc.yaml;

  # openclaw secrets — placed at the paths openclaw expects
  sops.secrets."openclaw-secrets-json" = {
    key = "openclaw/secretsJson";
    path = "${homeDir}/.openclaw/secrets/openclaw-secrets.json";
    mode = "0600";
  };

  sops.secrets."openclaw-telegram-bot-token" = {
    key = "openclaw/telegramBotToken";
    path = "${homeDir}/.openclaw/secrets/telegram-bot-token";
    mode = "0600";
  };

  # hermes-agent .env — sops places content at default path; hermesAgentBootstrap will symlink it
  sops.secrets."hermes-env" = {
    key = "hermes/envContent";
    mode = "0600";
  };

  # agent-deck conductor tokens
  sops.secrets."agentdeck-telegram-token" = {
    key = "agentDeck/telegramToken";
    mode = "0600";
  };

  sops.secrets."agentdeck-slack-bot-token" = {
    key = "agentDeck/slackBotToken";
    mode = "0600";
  };

  sops.secrets."agentdeck-slack-app-token" = {
    key = "agentDeck/slackAppToken";
    mode = "0600";
  };

  # shell secrets — sourced in zsh instead of $HOME/.secrets
  sops.secrets."shell-secrets" = {
    key = "shell/secrets";
    mode = "0600";
  };
}
