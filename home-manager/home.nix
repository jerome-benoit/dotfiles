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
    stateVersion = "25.11";
    enableNixpkgsReleaseCheck = false;
  };

  specialisation = {
    work = {
      configuration =
        let
          gpgKeyId = "27B535D3";
          gpgFingerprint = "B799 BBF6 8EC8 911B B8D7 CDBC C3B1 92C6 27B5 35D3";
        in
        {
          home.file.".signature".text = lib.mkForce ''
            Jérôme Benoit - R&D Software Engineer
            SAP Labs France
            OpenPGP Key ID : ${gpgKeyId}
            Key fingerprint : ${gpgFingerprint}
          '';

          programs.git.settings.user = {
            email = lib.mkForce "jerome.benoit@sap.com";
            signingKey = lib.mkForce gpgKeyId;
          };

          programs.zsh.shellAliases = {
            hm = lib.mkForce "nh home switch --specialisation work";
            hmw = "nh home switch --specialisation work";
            hmp = "nh home switch --specialisation personal";
          };
        };
    };

    personal = {
      configuration =
        let
          gpgKeyId = "27B535D3";
          gpgFingerprint = "B799 BBF6 8EC8 911B B8D7 CDBC C3B1 92C6 27B5 35D3";
        in
        {
          home.file.".signature".text = lib.mkForce ''
            Jérôme Benoit aka fraggle
            Piment Noir - https://piment-noir.org
            OpenPGP Key ID : ${gpgKeyId}
            Key fingerprint : ${gpgFingerprint}
          '';

          programs.git.settings.user = {
            email = lib.mkForce "jerome.benoit@piment-noir.org";
            signingKey = lib.mkForce gpgKeyId;
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
