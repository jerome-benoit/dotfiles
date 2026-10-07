{
  config,
  lib,
  pkgs,
  ...
}:

let
  homeDir = config.home.homeDirectory;
  sopsLaunchAgent = config.launchd.agents.sops-nix.config;
  sopsCommand = lib.escapeShellArgs (
    [ "/usr/bin/env" ]
    ++ lib.mapAttrsToList (
      name: value: "${name}=${toString value}"
    ) sopsLaunchAgent.EnvironmentVariables
    ++ [ (toString sopsLaunchAgent.Program) ]
  );
in
{
  sops = {
    age.keyFile =
      if pkgs.stdenv.hostPlatform.isDarwin then
        "${homeDir}/Library/Application Support/sops/age/keys.txt"
      else
        "${config.xdg.configHome}/sops/age/keys.txt";

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

    # Materialize secrets synchronously so decryption failures fail Home Manager activation.
    # launchd still refreshes them at login after setupLaunchAgents installs the agent.
    activation.sops-nix = lib.mkIf pkgs.stdenv.hostPlatform.isDarwin (
      lib.mkForce (
        lib.hm.dag.entryBetween [ "setupLaunchAgents" ] [ "writeBoundary" ] ''
          sopsServiceTarget="gui/$UID/org.nix-community.home.sops-nix"
          if /bin/launchctl print "$sopsServiceTarget" >/dev/null 2>&1; then
            darwinMajorVersion="$(/usr/bin/sw_vers --productVersion | /usr/bin/cut -d. -f1)"
            if [[ "$darwinMajorVersion" -ge 26 ]]; then
              run /bin/launchctl bootout --wait "$sopsServiceTarget"
            else
              run /bin/launchctl bootout "$sopsServiceTarget"
              run /bin/sleep 1
            fi
          fi

          run ${sopsCommand}
        ''
      )
    );

    file.".ssh/id_rsa.pub".source = ../../../secrets/ssh/id_rsa.pub;
  };
}
