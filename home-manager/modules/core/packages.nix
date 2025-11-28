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
        cask "gpg-suite@nightly"
        cask "jordanbaird-ice"
        cask "shuttle"
      '';
    };
    home.activation.brewBundle = lib.mkIf pkgs.stdenv.isDarwin (
      lib.hm.dag.entryAfter [ "writeBoundary" ] ''
        if command -v brew &> /dev/null; then
          $DRY_RUN_CMD echo "Executing brew bundle..."
          $DRY_RUN_CMD brew bundle --global --no-lock
          $DRY_RUN_CMD brew bundle cleanup --global --force
        fi
      ''
    );
  };
}
