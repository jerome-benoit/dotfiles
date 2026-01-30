{
  inputs,
  lib,
  config,
  pkgs,
  username,
  ...
}:
let
  hostname =
    if builtins.pathExists /etc/hostname then
      lib.removeSuffix "\n" (builtins.readFile /etc/hostname)
    else
      null;

  bunSupported = hostname != config.modules.core.constants.hosts.rigel;

  profileName =
    if hostname == config.modules.core.constants.hosts.ns3108029 then
      config.modules.core.constants.profiles.server
    else
      config.modules.core.constants.profiles.desktop;
  profileModules = config.modules.core.profile.modules;
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
    profile.name = profileName;
  };

  modules.shell = {
    direnv.enable = profileModules.shell.direnv;
    eza.enable = profileModules.shell.eza;
    fd.enable = profileModules.shell.fd;
    fzf.enable = profileModules.shell.fzf;
    ripgrep.enable = profileModules.shell.ripgrep;
    zoxide.enable = profileModules.shell.zoxide;
    zsh.enable = profileModules.shell.zsh;
  };

  modules.development = {
    bun.enable = bunSupported && profileModules.development.bun;
    gh.enable = profileModules.development.gh;
    git.enable = profileModules.development.git;
    lazygit.enable = profileModules.development.lazygit;
    opencode = {
      enable = bunSupported && profileModules.development.opencode.enable;
      enableDesktop = profileModules.development.opencode.enableDesktop;
    };
    openspec.enable = profileModules.development.openspec;
  };

  modules.programs = {
    alacritty.enable = profileModules.programs.alacritty;
    btop.enable = profileModules.programs.btop;
    ghostty.enable = profileModules.programs.ghostty;
    glow.enable = profileModules.programs.glow;
    himalaya.enable = profileModules.programs.himalaya;
    lazydocker.enable = profileModules.programs.lazydocker;
    ssh.enable = profileModules.programs.ssh;
    tmux.enable = profileModules.programs.tmux;
    zellij.enable = profileModules.programs.zellij;
  };

  modules.editors = {
    neovim = {
      enable = profileModules.editors.neovim.enable;
      plugins = {
        opencode.enable = bunSupported && profileModules.editors.neovim.plugins.opencode;
      };
    };
    vim.enable = profileModules.editors.vim;
  };

  home = {
    inherit username;
    homeDirectory = if pkgs.stdenv.isDarwin then "/Users/${username}" else "/home/${username}";
    stateVersion = "25.11";
    enableNixpkgsReleaseCheck = false;
  };
}
