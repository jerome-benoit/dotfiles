{
  inputs,
  lib,
  config,
  pkgs,
  username,
  ...
}:
let
  hostname = lib.removeSuffix "\n" (builtins.readFile /etc/hostname);
  bunSupported = !(hostname == "rigel");
in
{
  targets.genericLinux.enable = pkgs.stdenv.isLinux;

  systemd.user.startServices = if pkgs.stdenv.isLinux then "sd-switch" else "true";

  fonts.fontconfig.enable = true;

  imports = [
    ./modules
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

  modules.core = {
    home-manager.enable = true;
    packages.enable = true;
    specialisations.enable = true;
  };

  modules.shell = {
    direnv.enable = true;
    eza.enable = true;
    fd.enable = true;
    fzf.enable = true;
    ripgrep.enable = true;
    zoxide.enable = true;
    zsh.enable = true;
  };

  modules.development = {
    bun.enable = bunSupported;
    gh.enable = true;
    git.enable = true;
    opencode.enable = bunSupported;
  };

  modules.programs = {
    alacritty.enable = true;
    btop.enable = true;
    ghostty.enable = true;
    ssh.enable = true;
    tmux.enable = true;
  };

  modules.editors = {
    vim.enable = true;
    neovim = {
      enable = true;
      opencode.enable = bunSupported;
    };
  };

  home = {
    inherit username;
    homeDirectory = if pkgs.stdenv.isDarwin then "/Users/${username}" else "/home/${username}";
    stateVersion = "25.11";
    enableNixpkgsReleaseCheck = false;
  };
}
