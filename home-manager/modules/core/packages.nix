{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.modules.core.packages;
in
{
  options.modules.core.packages = {
    enable = lib.mkEnableOption "common packages";
  };

  config = lib.mkIf cfg.enable {
    home.packages = [
      pkgs.litellm
      pkgs.mergiraf
      pkgs.nerd-fonts.jetbrains-mono
      pkgs.nh
      pkgs.nixfmt
      pkgs.ollama
      pkgs.volta
      pkgs.whisper-cpp
    ]
    ++ lib.optionals pkgs.stdenv.isLinux (
      [ ]
      ++
        lib.optionals (config.modules.core.profile.name == config.modules.core.constants.profiles.server)
          [
            pkgs.delta
            pkgs.grc
          ]
    )
    ++ lib.optionals pkgs.stdenv.isDarwin [
      pkgs.autoconf
      pkgs.automake
      pkgs.bat
      (pkgs.bruno.override {
        nodejs_22 = pkgs.nodejs_22.override {
          nodejs-slim = pkgs.nodejs-slim_22.overrideAttrs { doCheck = false; };
        };
      })
      pkgs.chroma
      pkgs.cloudfoundry-cli
      pkgs.cmake
      pkgs.coreutils
      pkgs.delta
      pkgs.firefox
      pkgs.gnused
      pkgs.go
      pkgs.go-task
      pkgs.golangci-lint
      pkgs.gopls
      pkgs.google-chrome
      pkgs.grc
      pkgs.hyperfine
      pkgs.insomnia
      pkgs.iterm2
      pkgs.jdk25
      pkgs.jetbrains.pycharm
      pkgs.jetbrains.rust-rover
      pkgs.lychee
      pkgs.mitmproxy
      pkgs.nheko
      pkgs.ninja
      pkgs.pass
      pkgs.pipenv
      pkgs.pkg-config
      pkgs.podman
      pkgs.podman-compose
      pkgs.podman-desktop
      pkgs.poetry
      pkgs.python3
      pkgs.python3Packages.virtualenv
      pkgs.qpdf
      pkgs.rectangle
      pkgs.ruff
      pkgs.rustup
      pkgs.uv
      pkgs.vscode
      pkgs.yq
      (pkgs.zed-editor.overrideAttrs (oldAttrs: {
        doCheck = false;
      }))
      pkgs.zoom-us
    ];

    home.file.".Brewfile" = lib.mkIf pkgs.stdenv.isDarwin {
      text = ''
        tap "hAIperspace/hai", "https://github.tools.sap/hAIperspace/hai-homebrew"
        tap "moltenbits/tap"
        tap "steipete/tap"
        cask "docker-desktop"
        cask "ferdium"
        cask "ghostty"
        cask "gpg-suite@nightly"
        cask "jordanbaird-ice"
        cask "shuttle"
        cask "moltenbits/tap/growlrrr"
        brew "hai"
        brew "mole"
        brew "steipete/tap/peekaboo"
      '';
    };
    home.activation.brewBundle = lib.mkIf pkgs.stdenv.isDarwin (
      lib.hm.dag.entryAfter [ "linkGeneration" ] ''
        _brew=""
        if [[ -f /opt/homebrew/bin/brew ]]; then
          _brew=/opt/homebrew/bin/brew
        elif [[ -f /usr/local/bin/brew ]]; then
          _brew=/usr/local/bin/brew
        fi

        if [[ -n "$_brew" ]]; then
          if command -v gh >/dev/null 2>&1; then
            _gh_sap_token=$(gh auth token --hostname github.tools.sap 2>/dev/null)
            if [[ -n "$_gh_sap_token" ]]; then
              export HOMEBREW_GITHUB_API_TOKEN="$_gh_sap_token"
            fi
          fi

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
