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

  # Mic92/sops-nix#581 (Linux: activation before daemon-reload)
  home.activation.reloadSystemdBeforeSops = lib.mkIf pkgs.stdenv.isLinux (
    lib.hm.dag.entryBetween [ "sops-nix" ] [ "reloadSystemd" ] ""
  );

  # Mic92/sops-nix#910 (macOS: activation before plist installed)
  home.activation.sops-nix = lib.mkIf pkgs.stdenv.isDarwin (
    lib.hm.dag.entryAfter [ "setupLaunchAgents" ] ''
      /bin/launchctl bootout gui/$(id -u ${config.home.username})/org.nix-community.home.sops-nix && true
      PLIST="${homeDir}/Library/LaunchAgents/org.nix-community.home.sops-nix.plist"
      if [ -f "$PLIST" ]; then
        /bin/launchctl bootstrap gui/$(id -u ${config.home.username}) "$PLIST"
      fi
    ''
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

  sops.secrets."ssh-id-rsa" = {
    format = "binary";
    sopsFile = ../../../secrets/ssh/id_rsa;
    path = "${homeDir}/.ssh/id_rsa";
  };

  home.file.".ssh/id_rsa.pub".source = ../../../secrets/ssh/id_rsa.pub;
}
