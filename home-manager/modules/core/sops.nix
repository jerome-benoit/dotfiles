{
  config,
  ...
}:

let
  homeDir = config.home.homeDirectory;
in
{
  sops.gnupg.home = "${homeDir}/.gnupg";
  sops.gnupg.sshKeyPaths = [ ];

  sops.defaultSopsFile = ../../../secrets/tokens.enc.yaml;

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

  # hermesAgentBootstrap will symlink this to the expected location
  sops.secrets."hermes-env" = {
    key = "hermes/envContent";
    mode = "0600";
  };

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

  # replaces $HOME/.secrets
  sops.secrets."shell-secrets" = {
    key = "shell/secrets";
    mode = "0600";
  };
}
