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
    home.packages =
      with pkgs;
      [
        bun
        nerd-fonts.jetbrains-mono
        nh
        nixfmt-rfc-style
        opencode
        volta
      ]
      ++ lib.optionals pkgs.stdenv.isLinux [
      ]
      ++ lib.optionals pkgs.stdenv.isDarwin [
        bruno
        chroma
        cloudfoundry-cli
        delta
        firefox
        go
        google-chrome
        grc
        hyperfine
        insomnia
        iterm2
        jdk25
        jetbrains.pycharm-community-bin
        jetbrains.rust-rover
        kubectl
        mergiraf
        nheko
        ninja
        pipenv
        podman
        podman-compose
        podman-desktop
        poetry
        python3
        qpdf
        rectangle
        rustup
        uv
        vscode
        zed-editor
        zoom-us
      ];

    home.file.".Brewfile" = lib.mkIf pkgs.stdenv.isDarwin {
      text = ''
        cask "docker-desktop"
        cask "ferdium"
        cask "ghostty"
        cask "gpg-suite@nightly"
        cask "jordanbaird-ice"
        cask "shuttle"
      '';
    };
    home.activation.brewBundle = lib.mkIf pkgs.stdenv.isDarwin (
      lib.hm.dag.entryAfter [ "writeBoundary" ] ''
        if [ -f /opt/homebrew/bin/brew ]; then
          verboseEcho "Installing Homebrew packages from Brewfile"
          run /opt/homebrew/bin/brew bundle install --global
          run /opt/homebrew/bin/brew bundle cleanup --global --force
        elif [ -f /usr/local/bin/brew ]; then
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
