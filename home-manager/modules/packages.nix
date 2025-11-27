{ pkgs, lib, ... }:

{
  home.packages =
    with pkgs;
    [
      bun
      gh
      nh
      nixfmt-rfc-style
      opencode
      volta
    ]
    ++ lib.optionals pkgs.stdenv.isLinux [
    ]
    ++ lib.optionals pkgs.stdenv.isDarwin [
      alacritty
      bruno
      btop
      chroma
      cloudfoundry-cli
      delta
      direnv
      eza
      fd
      firefox
      fzf
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
      neovim
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
      ripgrep
      rustup
      tmux
      uv
      vim
      vscode
      zed-editor
      zoxide
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
}
