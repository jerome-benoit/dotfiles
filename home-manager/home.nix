{
  inputs,
  lib,
  config,
  pkgs,
  username,
  constants,
  ...
}:
let
  hostname =
    if builtins.pathExists /etc/hostname then
      lib.removeSuffix "\n" (builtins.readFile /etc/hostname)
    else
      null;

  hosts = config.modules.core.constants.hosts;
  bunSupported = hostname != hosts.rigel;
  crushSupported = hostname != hosts.faust;
  isSway = hostname == hosts.zeus;

  profileName =
    if hostname == hosts.ns3108029 then constants.profiles.server else constants.profiles.desktop;
  profileModules = config.modules.core.profile.modules;
in
{
  targets.genericLinux.enable = pkgs.stdenv.hostPlatform.isLinux;

  systemd.user.startServices = lib.mkIf pkgs.stdenv.hostPlatform.isLinux "sd-switch";

  fonts.fontconfig.enable = true;

  imports = [
    ./modules
  ];

  nixpkgs = {
    overlays = [
      inputs.nix-openclaw.overlays.default
      inputs.hermes-agent.overlays.default
      (
        _: prev:
        lib.optionalAttrs prev.stdenv.hostPlatform.isDarwin {
          python313 = prev.python313.override {
            packageOverrides = _: pprev: {
              a2a-sdk = pprev.a2a-sdk.overrideAttrs (old: {
                disabledTests = (old.disabledTests or [ ]) ++ [
                  "test_notification_triggering"
                ];
              });
            };
          };
        }
      )
    ];
    config = {
      allowUnfree = true;
      permittedInsecurePackages = lib.optionals pkgs.stdenv.hostPlatform.isDarwin [
        "olm-3.2.16"
      ];
    };
  };

  modules.core = {
    gpg.enable = true;
    home-manager.enable = true;
    gpu.enable = pkgs.stdenv.hostPlatform.isLinux && profileName == constants.profiles.desktop;
    packages = {
      enable = true;
      inherit crushSupported;
    };
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
    agent-deck.enable = profileModules.development.agentDeck;
    agtx.enable = profileModules.development.agtx;
    aoe = {
      enable = profileModules.development.aoe.enable;
      enableWeb = profileModules.development.aoe.enableWeb;
    };
    bun.enable = bunSupported && profileModules.development.bun;
    claudeCode.enable = bunSupported && profileModules.development.claudeCode;
    gh.enable = profileModules.development.gh;
    git.enable = profileModules.development.git;
    hermesAgent = {
      enable = profileModules.development.hermesAgent.enable;
      enableDashboard = profileModules.development.hermesAgent.enableDashboard;
      enableDesktop = profileModules.development.hermesAgent.enableDesktop;
      enableGateway = profileModules.development.hermesAgent.enableGateway;
    };
    lazygit.enable = profileModules.development.lazygit;
    opencode = {
      enable = bunSupported && profileModules.development.opencode.enable;
      enableDesktop = profileModules.development.opencode.enableDesktop;
    };
    openspec.enable = profileModules.development.openspec;
    openclaw.enable = profileModules.development.openclaw;
    pi.enable = profileModules.development.pi;
    qmd.enable = bunSupported && profileModules.development.qmd;
  };

  modules.programs = {
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
    homeDirectory =
      if pkgs.stdenv.hostPlatform.isDarwin then "/Users/${username}" else "/home/${username}";
    stateVersion = "26.05";
    enableNixpkgsReleaseCheck = false;
  };
}
