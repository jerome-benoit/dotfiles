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
  sops.age.keyFile = "${homeDir}/.config/sops/age/keys.txt";

  sops.defaultSopsFile = ../../../secrets/tokens.enc.yaml;

  # --- sops-nix activation ordering fixes ---

  # Linux: ensure sops-nix activation runs after systemd daemon-reload (Mic92/sops-nix#581)
  home.activation.reloadSystemdBeforeSops = lib.mkIf pkgs.stdenv.isLinux (
    lib.hm.dag.entryBetween [ "sops-nix" ] [ "reloadSystemd" ] ""
  );

  # macOS: ensure sops-nix activation runs after plist is installed (Mic92/sops-nix#910)
  home.activation.sops-nix = lib.mkIf pkgs.stdenv.isDarwin (
    lib.mkForce (
      lib.hm.dag.entryAfter [ "setupLaunchAgents" ] ''
        /bin/launchctl bootout gui/$(id -u ${config.home.username})/org.nix-community.home.sops-nix || true
        PLIST="${homeDir}/Library/LaunchAgents/org.nix-community.home.sops-nix.plist"
        if [ -f "$PLIST" ]; then
          /bin/launchctl bootstrap gui/$(id -u ${config.home.username}) "$PLIST"
        fi
      ''
    )
  );

  # --- Secrets declarations ---

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
