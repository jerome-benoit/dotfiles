{
  config,
  lib,
  pkgs,
  inputs,
  ...
}:
let
  cfg = config.modules.core.packages;
  constants = config.modules.core.constants;
  openclawEnabled = config.modules.development.openclaw.enable or false;
  openclawTools = inputs.nix-openclaw-tools.packages.${pkgs.stdenv.hostPlatform.system};
  isDesktop = config.modules.core.profile.name == config.modules.core.constants.profiles.desktop;
  isServer = config.modules.core.profile.name == config.modules.core.constants.profiles.server;
  isDarwin = pkgs.stdenv.hostPlatform.isDarwin;
  isLinux = pkgs.stdenv.hostPlatform.isLinux;
in
{
  options.modules.core.packages = {
    enable = lib.mkEnableOption "common packages";
    crushSupported = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Whether crush is supported on this host";
    };
  };

  config = lib.mkIf cfg.enable {
    home.packages = [
      pkgs.litellm
      pkgs.mergiraf
      pkgs.nh
      pkgs.ollama
      pkgs.volta
      pkgs.whisper-cpp
    ]
    ++ lib.optionals (!openclawEnabled) [
      openclawTools.camsnap
      openclawTools.discrawl
      openclawTools.gogcli
      openclawTools.goplaces
      openclawTools.sag
      openclawTools.sonoscli
      openclawTools.summarize
      openclawTools.wacrawl
    ]
    ++ lib.optionals isServer [
      pkgs.delta
      pkgs.grc
    ]
    ++ lib.optionals (isServer && isLinux) [
    ]
    ++ lib.optionals isDesktop [
      pkgs.bruno
      pkgs.cloudfoundry-cli
      pkgs.codex
      pkgs.gemini-cli
      pkgs.lychee
      pkgs.nerd-fonts.jetbrains-mono
      pkgs.nil
      pkgs.nixfmt
      pkgs.obsidian
      pkgs.yazi
    ]
    ++ lib.optionals (isDesktop && cfg.crushSupported) [
      pkgs.crush
    ]
    ++ lib.optionals (isDesktop && isDarwin) (
      [
        pkgs.age
        pkgs.autoconf
        pkgs.automake
        pkgs.bashInteractive
        pkgs.bat
        pkgs.chroma
        pkgs.cmake
        pkgs.coreutils
        pkgs.delta
        pkgs.ffmpeg
        pkgs.firefox
        pkgs.gnused
        pkgs.go
        pkgs.go-task
        pkgs.golangci-lint
        pkgs.google-chrome
        pkgs.gopls
        pkgs.grc
        pkgs.hyperfine
        pkgs.insomnia
        pkgs.iterm2
        pkgs.jdk25
        pkgs.jetbrains.pycharm
        pkgs.jetbrains.rust-rover
        pkgs.mitmproxy
        pkgs.nheko
        pkgs.ninja
        pkgs.pandoc
        pkgs.pass
        pkgs.pipenv
        pkgs.pkg-config
        pkgs.podman
        pkgs.podman-compose
        pkgs.podman-desktop
        pkgs.poetry
        pkgs.poppler-utils
        pkgs.python3
        pkgs.python3Packages.virtualenv
        pkgs.qpdf
        pkgs.rectangle
        pkgs.ruff
        pkgs.rustup
        pkgs.uv
        pkgs.vscode
        pkgs.yq
        pkgs.zed-editor
        pkgs.zoom-us
      ]
      ++ lib.optionals (!openclawEnabled) [
        openclawTools.imsg
        openclawTools.peekaboo
        openclawTools.poltergeist
      ]
    )
    ++ lib.optionals (isDesktop && isLinux) [
    ];

    home.file.".Brewfile" = lib.mkIf (isDesktop && isDarwin) {
      text = ''
        tap "hAIperspace/hai", "https://${constants.work.gheHostname}/hAIperspace/hai-homebrew"
        tap "moltenbits/tap"
        cask "docker-desktop"
        cask "ferdium"
        cask "ghostty"
        cask "gpg-suite@nightly"
        cask "jordanbaird-ice"
        cask "moltenbits/tap/growlrrr"
        brew "hai"
        brew "mole"
      '';
    };
    home.activation.brewBundle = lib.mkIf (isDesktop && isDarwin) (
      lib.hm.dag.entryAfter [ "linkGeneration" ] ''
        _brew=""
        if [[ -f /opt/homebrew/bin/brew ]]; then
          _brew=/opt/homebrew/bin/brew
        elif [[ -f /usr/local/bin/brew ]]; then
          _brew=/usr/local/bin/brew
        fi

        if [[ -n "$_brew" ]]; then
          _gh_sap_token=$(${lib.getExe pkgs.gh} auth token --hostname "${constants.work.gheHostname}" 2>/dev/null || true)
          if [[ -n "$_gh_sap_token" ]]; then
            export HOMEBREW_GITHUB_API_TOKEN="$_gh_sap_token"
          fi

          "$_brew" trust --formula haiperspace/hai/hai 2>/dev/null || true
          "$_brew" trust --formula haiperspace/hai/mole 2>/dev/null || true
          "$_brew" trust --cask moltenbits/tap/growlrrr 2>/dev/null || true

          verboseEcho "Installing Homebrew packages from Brewfile"
          run "$_brew" bundle install --global
          run "$_brew" bundle cleanup --global --force

          unset _gh_sap_token
        else
          warnEcho "Homebrew not found"
        fi
        unset _brew
      ''
    );
  };
}
