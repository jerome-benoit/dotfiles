{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.programs.syncthing;
  isDarwin = pkgs.stdenv.hostPlatform.isDarwin;
in
{
  options.modules.programs.syncthing = {
    enable = lib.mkEnableOption "syncthing configuration";
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = isDarwin;
        message = "modules.programs.syncthing is macOS-only. On Linux, syncthing is managed by the distribution.";
      }
    ];

    services.syncthing = {
      enable = true;

      overrideDevices = false;
      overrideFolders = false;

      settings.options = {
        urAccepted = -1;
        relaysEnabled = false;
        localAnnounceEnabled = true;
      };
    };
  };
}
