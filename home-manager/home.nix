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

  bunSupported = hostname != config.modules.core.constants.hosts.rigel;

  isSway = hostname == config.modules.core.constants.hosts.zeus;

  nvidiaVersion =
    if builtins.pathExists /proc/driver/nvidia/version then
      let
        raw = builtins.readFile /proc/driver/nvidia/version;
        match = builtins.match "NVRM version:.*Module[[:space:]]+([0-9.]+)[^\n]*\n.*" raw;
      in
      if match != null then builtins.head match else null
    else
      null;

  nvidiaArch = if pkgs.stdenv.hostPlatform.isx86_64 then "x86_64" else "aarch64";
  nvidiaDriverSri =
    let
      url = "https://download.nvidia.com/XFree86/Linux-${nvidiaArch}/${nvidiaVersion}/NVIDIA-Linux-${nvidiaArch}-${nvidiaVersion}.run";
      hash = builtins.hashFile "sha256" (builtins.fetchurl url);
    in
    builtins.convertHash {
      inherit hash;
      toHashFormat = "sri";
      hashAlgo = "sha256";
    };

  profileName =
    if hostname == config.modules.core.constants.hosts.ns3108029 then
      constants.profiles.server
    else
      constants.profiles.desktop;
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
      # https://github.com/openclaw/nix-openclaw/issues/80
      (_final: prev: {
        openclaw-gateway = prev.openclaw-gateway.overrideAttrs (old: {
          postPatch = (old.postPatch or "") + ''
            if [ -f scripts/stage-bundled-plugin-runtime-deps.mjs ]; then
              sed -i '/const result = spawnSync(npmRunner\.command/i\
              console.warn(`[nix] skipping npm install for ''${pluginId}`); return;' \
                scripts/stage-bundled-plugin-runtime-deps.mjs
            fi
          '';
        });
      })
    ];
    config = {
      allowUnfree = true;
      permittedInsecurePackages = lib.optionals pkgs.stdenv.hostPlatform.isDarwin [
        "electron-38.8.4"
        "olm-3.2.16"
      ];
    };
  };

  modules.core = {
    home-manager.enable = true;
    gpu = {
      enable = pkgs.stdenv.hostPlatform.isLinux && profileName == constants.profiles.desktop;
      nvidia = lib.mkIf (nvidiaVersion != null) {
        enable = true;
        version = nvidiaVersion;
        sha256 = nvidiaDriverSri;
      };
    };
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
    agent-deck.enable = profileModules.development.agentDeck;
    agtx.enable = profileModules.development.agtx;
    aoe = {
      enable = profileModules.development.aoe.enable;
      enableWeb = profileModules.development.aoe.enableWeb;
    };
    bun.enable = bunSupported && profileModules.development.bun;
    claudeCode.enable = profileModules.development.claudeCode;
    gh.enable = profileModules.development.gh;
    git.enable = profileModules.development.git;
    hermes.enable = profileModules.development.hermes;
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
