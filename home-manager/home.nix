{
  lib,
  config,
  pkgs,
  profile,
  username,
  ...
}:
let
  constants = config.modules.core.constants;
  hostname = constants.hostname;
  hosts = constants.hosts;
  bunSupported = hostname != hosts.rigel;
  antigravitySupported = hostname != hosts.rigel;
  crushSupported = hostname != hosts.faust;
  isSway = hostname == hosts.zeus;

  profileModules = config.modules.core.profile.modules;
in
{
  targets.genericLinux.enable = pkgs.stdenv.hostPlatform.isLinux;

  systemd.user.startServices = lib.mkIf pkgs.stdenv.hostPlatform.isLinux "sd-switch";

  fonts.fontconfig.enable = true;

  imports = [
    ./modules
  ];

  modules = {
    core = {
      email.enable = profileModules.core.email;
      gpg.enable = true;
      home-manager.enable = true;
      gpu.enable = pkgs.stdenv.hostPlatform.isLinux;
      packages = {
        enable = true;
        inherit antigravitySupported crushSupported;
      };
      specialisations.enable = true;
      profile.name = profile;
    };

    shell = {
      direnv.enable = profileModules.shell.direnv;
      eza.enable = profileModules.shell.eza;
      fd.enable = profileModules.shell.fd;
      fzf.enable = profileModules.shell.fzf;
      ripgrep.enable = profileModules.shell.ripgrep;
      zoxide.enable = profileModules.shell.zoxide;
      zsh.enable = profileModules.shell.zsh;
    };

    development = {
      agtx.enable = profileModules.development.agtx;
      aoe = {
        enable = profileModules.development.aoe.enable;
        enableWeb = profileModules.development.aoe.enableWeb;
      };
      bun.enable = bunSupported && profileModules.development.bun;
      claudeCode.enable = bunSupported && profileModules.development.claudeCode;
      colibri.enable = profileModules.development.colibri;
      gh.enable = profileModules.development.gh;
      git.enable = profileModules.development.git;
      herdr.enable = profileModules.development.herdr;
      hermesAgent = {
        inherit (profileModules.development.hermesAgent)
          enable
          enableDashboard
          enableDesktop
          enableGateway
          ;
      };
      lazygit.enable = profileModules.development.lazygit;
      omp.enable = bunSupported && profileModules.development.omp;
      opencode = {
        enable = bunSupported && profileModules.development.opencode.enable;
        enableDesktop = profileModules.development.opencode.enableDesktop;
      };
      openspec.enable = profileModules.development.openspec;
      openclaw.enable = profileModules.development.openclaw;
      pi.enable = profileModules.development.pi;
      primeAgent.enable = profileModules.development.primeAgent;
      qmd.enable = bunSupported && profileModules.development.qmd;
    };

    programs = {
      alacritty.enable = profileModules.programs.alacritty;
      btop.enable = profileModules.programs.btop;
      ghostty.enable = profileModules.programs.ghostty;
      glow.enable = profileModules.programs.glow;
      himalaya.enable = profileModules.programs.himalaya;
      lazydocker.enable = profileModules.programs.lazydocker;
      sway.enable = isSway && profileModules.programs.sway;
      ssh.enable = profileModules.programs.ssh;
      sshm.enable = profileModules.programs.sshm;
      syncthing.enable = pkgs.stdenv.hostPlatform.isDarwin && profileModules.programs.syncthing;
      tmux.enable = profileModules.programs.tmux;
      zellij.enable = profileModules.programs.zellij;
    };

    editors = {
      neovim = {
        enable = profileModules.editors.neovim.enable;
        plugins = {
          opencode.enable = bunSupported && profileModules.editors.neovim.plugins.opencode;
        };
      };
      vim.enable = profileModules.editors.vim;
    };
  };

  home = {
    inherit username;
    homeDirectory =
      if pkgs.stdenv.hostPlatform.isDarwin then "/Users/${username}" else "/home/${username}";
    stateVersion = "26.05";
    enableNixpkgsReleaseCheck = false;
  };
}
