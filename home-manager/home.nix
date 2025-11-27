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
      permittedInsecurePackages = lib.optionals pkgs.stdenv.isDarwin [
        "olm-3.2.16"
      ];
    };
  };

  home = {
    inherit username;
    homeDirectory = if pkgs.stdenv.isDarwin then "/Users/${username}" else "/home/${username}";
    stateVersion = "26.05";
    enableNixpkgsReleaseCheck = false;
  };

  specialisation = {
    work = {
      configuration = {
        programs.git.settings.user = {
          email = lib.mkForce "jerome.benoit@sap.com";
          signingKey = lib.mkForce "27B535D3";
        };

        programs.zsh.shellAliases = {
          hm = lib.mkForce "nh home switch --specialisation work";
          hmw = "nh home switch --specialisation work";
          hmp = "nh home switch --specialisation personal";
        };
      };
    };

    personal = {
      configuration = {
        programs.git.settings.user = {
          email = lib.mkForce "jerome.benoit@piment-noir.org";
          signingKey = lib.mkForce "27B535D3";
        };

        programs.zsh.shellAliases = {
          hm = lib.mkForce "nh home switch --specialisation personal";
          hmw = "nh home switch --specialisation work";
          hmp = "nh home switch --specialisation personal";
        };
      };
    };
  };
}
