{
  config,
  lib,
  pkgs,
  inputs,
  ...
}:
let
  cfg = config.modules.development.openclaw;
  desktopPackage =
    if pkgs.stdenv.hostPlatform.isDarwin then
      inputs.nix-openclaw.packages.${pkgs.stdenv.hostPlatform.system}.openclaw-app
    else
      pkgs.callPackage ./openclaw-linux-package.nix { };
in
{
  options.modules.development.openclaw = {
    enable = lib.mkEnableOption "OpenClaw desktop application";
  };

  config = lib.mkIf cfg.enable {
    # Install only the official desktop client; gateway setup belongs to the app.
    home.packages = [ desktopPackage ];
  };
}
