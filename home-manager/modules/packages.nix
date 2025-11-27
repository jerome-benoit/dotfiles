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
      poetry
      podman
      podman-compose
      podman-desktop
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
      zoom-us
      zoxide
    ];
}
