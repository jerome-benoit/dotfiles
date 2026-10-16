{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.modules.core.home-manager;
  nixPackage =
    if config.nix.enable && config.nix.package != null then config.nix.package else pkgs.nix;
in
{
  options.modules.core.home-manager = {
    enable = lib.mkEnableOption "home-manager configuration";
  };

  config = lib.mkIf cfg.enable {
    programs.home-manager.enable = true;

    nix = {
      package = lib.mkDefault pkgs.nix;
      settings = {
        experimental-features = [
          "nix-command"
          "flakes"
        ];
        warn-dirty = false;
      };
      gc = {
        automatic = true;
        dates = "weekly";
        options = "--delete-older-than 30d";
      };
    };

    # Workaround: Home Manager passes GC options as one launchd argument.
    # Remove when upstream preserves shell option semantics on Darwin.
    launchd.agents.nix-gc.config.ProgramArguments =
      lib.mkIf (pkgs.stdenv.hostPlatform.isDarwin && config.nix.gc.automatic)
        (
          lib.mkForce [
            pkgs.runtimeShell
            "-c"
            "exec ${lib.escapeShellArg (lib.getExe' nixPackage "nix-collect-garbage")} ${
              lib.optionalString (config.nix.gc.options != null) config.nix.gc.options
            }"
          ]
        );
  };
}
