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
      pkgs.bruno
      pkgs.chroma
      pkgs.cloudfoundry-cli
      pkgs.cmake
      pkgs.coreutils
      pkgs.delta
      pkgs.firefox
      pkgs.gnused
      pkgs.go
      pkgs.google-chrome
      pkgs.grc
      pkgs.hyperfine
      pkgs.insomnia
      pkgs.iterm2
      pkgs.jdk25
      # pkgs.jetbrains.pycharm
      pkgs.jetbrains.rust-rover
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
        tap "steipete/tap"
        cask "docker-desktop"
        cask "ferdium"
        cask "ghostty"
        cask "gpg-suite@nightly"
        cask "jordanbaird-ice"
        cask "shuttle"
        brew "steipete/tap/peekaboo"
      '';
    };
    home.activation.brewBundle = lib.mkIf pkgs.stdenv.isDarwin (
      lib.hm.dag.entryAfter [ "writeBoundary" ] ''
        if [[ -f /opt/homebrew/bin/brew ]]; then
          verboseEcho "Installing Homebrew packages from Brewfile"
          run /opt/homebrew/bin/brew bundle install --global
          run /opt/homebrew/bin/brew bundle cleanup --global --force
        elif [[ -f /usr/local/bin/brew ]]; then
          verboseEcho "Installing Homebrew packages from Brewfile"
          run /usr/local/bin/brew bundle install --global
          run /usr/local/bin/brew bundle cleanup --global --force
        else
          warnEcho "Homebrew not found at /opt/homebrew/bin/brew or /usr/local/bin/brew"
        fi
      ''
    );
  };
}
