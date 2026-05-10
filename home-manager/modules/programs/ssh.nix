{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.programs.ssh;
  mkSystemPackage = config.modules.core.lib.mkSystemPackage;
  homeDir = config.home.homeDirectory;

  # sshm manages hosts in this mutable file; SSH reads it via Include.
  hostsFile = "${homeDir}/.ssh/hosts.local";
in
{
  options.modules.programs.ssh = {
    enable = lib.mkEnableOption "ssh configuration";
  };

  config = lib.mkIf cfg.enable {
    programs.ssh = lib.mkMerge [
      {
        enable = true;
        enableDefaultConfig = false;
        package = mkSystemPackage "ssh" { };
        includes = [ hostsFile ];
        matchBlocks = {
          "*" = {
            addKeysToAgent = "yes";
            forwardAgent = true;
            forwardX11 = true;
          };
        };
      }
      (lib.mkIf pkgs.stdenv.hostPlatform.isDarwin {
        matchBlocks = {
          "*" = {
            extraOptions = {
              UseKeychain = "yes";
            };
          };
        };
      })
    ];

    # Seed the mutable hosts file if absent.
    home.activation.sshHostsFile = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
      if [[ ! -f "${hostsFile}" ]]; then
        run touch "${hostsFile}"
        run chmod 600 "${hostsFile}"
      fi
    '';

    # Shell alias so sshm always targets the mutable file.
    programs.bash.shellAliases.sshm = "sshm -c ${hostsFile}";
    programs.zsh.shellAliases.sshm = "sshm -c ${hostsFile}";
  };
}
