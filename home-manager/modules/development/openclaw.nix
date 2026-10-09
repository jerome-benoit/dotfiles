{
  config,
  lib,
  pkgs,
  inputs,
  ...
}:
let
  cfg = config.modules.development.openclaw;
in
{
  options.modules.development.openclaw = {
    enable = lib.mkEnableOption "OpenClaw desktop application (macOS only)";
  };

  config = lib.mkIf (cfg.enable && pkgs.stdenv.hostPlatform.isDarwin) {
    # Use the app-only component, not the gateway/tools bundle or service module.
    home.packages = [
      inputs.nix-openclaw.packages.${pkgs.stdenv.hostPlatform.system}.openclaw-app
    ];
  };
}
