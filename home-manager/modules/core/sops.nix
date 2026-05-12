{
  config,
  lib,
  pkgs,
  ...
}:

let
  homeDir = config.home.homeDirectory;
in
{
  sops.gnupg.home = "${homeDir}/.gnupg";
  sops.gnupg.sshKeyPaths = [ ];

  sops.defaultSopsFile = ../../../secrets/tokens.enc.yaml;

  # Mic92/sops-nix#581
  home.activation.reloadSystemdBeforeSops = lib.mkIf pkgs.stdenv.isLinux (
    lib.hm.dag.entryBetween [ "sops-nix" ] [ "reloadSystemd" ] ""
  );

  # hermesAgentBootstrap will symlink this to the expected location
  sops.secrets."hermes-env" = {
    key = "hermes/personal/envContent";
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
