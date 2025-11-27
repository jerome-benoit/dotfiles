{
  inputs,
  lib,
  config,
  pkgs,
  username,
  ...
}:
{
  targets.genericLinux.enable = pkgs.stdenv.isLinux;

  systemd.user.startServices = if pkgs.stdenv.isLinux then "sd-switch" else "true";

  imports = [
    ./modules/git.nix
    ./modules/home-manager.nix
    ./modules/packages.nix
    ./modules/ssh.nix
    ./modules/zsh.nix
  ];

  nixpkgs = {
    overlays = [
    ];
    config = {
      allowUnfree = true;
    };
  };

  home = {
    inherit username;
    homeDirectory = if pkgs.stdenv.isDarwin then "/Users/${username}" else "/home/${username}";
    stateVersion = "26.05";
    enableNixpkgsReleaseCheck = false;
  };
}
