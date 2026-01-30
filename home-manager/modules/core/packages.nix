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
        mergiraf
        nerd-fonts.jetbrains-mono
        nh
        nixfmt
        volta
      ]
      ++ lib.optionals pkgs.stdenv.isLinux (
        [ ]
        ++
          lib.optionals (config.modules.core.profile.name == config.modules.core.constants.profiles.server)
            [
              delta
              grc
            ]
      )
      ++ lib.optionals pkgs.stdenv.isDarwin [
        autoconf
        automake
        bat
        bruno
        chroma
        cloudfoundry-cli
        cmake
        coreutils
        delta
        firefox
        gnused
        go
        google-chrome
        grc
        hyperfine
        insomnia
        iterm2
        jdk25
        jetbrains.pycharm-community-bin
        jetbrains.rust-rover
        mitmproxy
        nheko
        ninja
        pass
        pipenv
        pkg-config
        podman
        podman-compose
        podman-desktop
        poetry
        python3
        python3Packages.virtualenv
        qpdf
        rectangle
        ruff
        rustup
        uv
        vscode
        yq
        (zed-editor.overrideAttrs (oldAttrs: {
          doCheck = false;
        }))
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
