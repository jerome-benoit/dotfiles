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
  sops = {
    age.keyFile = "${homeDir}/.config/sops/age/keys.txt";

    defaultSopsFile = ../../../secrets/credentials.enc.yaml;

    # --- Secrets declarations ---

    secrets = {
      "hermes-env" = {
        key = "hermes/personal/envContent";
        mode = "0600";
      };

      "shell-secrets" = {
        key = "shell/secrets";
        mode = "0600";
      };

      "ssh-id-rsa" = {
        format = "binary";
        sopsFile = ../../../secrets/ssh/id_rsa;
        path = "${homeDir}/.ssh/id_rsa";
      };
    };
  };

  home = {
    # Workaround: sops-nix may restart the service before Home Manager creates it.
    # Remove when upstream orders sops-nix after reloadSystemd.
    activation.reloadSystemdBeforeSops = lib.mkIf pkgs.stdenv.hostPlatform.isLinux (
      lib.hm.dag.entryBetween [ "sops-nix" ] [ "reloadSystemd" ] ""
    );

    # Workaround: sops-nix may bootstrap launchd before installing its plist.
    # Remove when upstream orders sops-nix after setupLaunchAgents.
    activation.sops-nix = lib.mkIf pkgs.stdenv.hostPlatform.isDarwin (
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

    file.".ssh/id_rsa.pub".source = ../../../secrets/ssh/id_rsa.pub;
  };
}
