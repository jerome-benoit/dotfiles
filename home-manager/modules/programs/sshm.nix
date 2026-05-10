{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.programs.sshm;
  homeDir = config.home.homeDirectory;
  hostsFile = "${homeDir}/.ssh/hosts.local";
in
{
  options.modules.programs.sshm = {
    enable = lib.mkEnableOption "sshm SSH manager";
  };

  config = lib.mkIf cfg.enable {
    home.packages = [ pkgs.sshm ];

    # Include mutable hosts file in SSH config.
    programs.ssh.includes = [ hostsFile ];

    # Seed the mutable hosts file if absent.
    home.activation.sshHostsFile = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
      if [[ ! -f "${hostsFile}" ]]; then
        run touch "${hostsFile}"
        run chmod 600 "${hostsFile}"
      fi
    '';
  };
}
