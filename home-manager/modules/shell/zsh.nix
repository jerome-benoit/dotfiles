{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.shell.zsh;
  distroId = config.modules.core.distro.id;
  distroIds = config.modules.core.distro.ids;
  systemZsh = pkgs.runCommand "zsh-system" { } "mkdir -p $out";
in
{
  options.modules.shell.zsh = {
    enable = lib.mkEnableOption "zsh configuration";
  };

  config = lib.mkIf cfg.enable {
    programs.zsh = {
      enable = true;
      package = systemZsh;
      sessionVariables = {
        NH_FLAKE = "$HOME/.nix";
        DVM_DIR = "$HOME/.dvm";
        WORKSPACE = "$HOME/tmp";
      };
      shellAliases = {
        hm = "nh home switch --impure";
      };
      oh-my-zsh = {
        enable = true;
        theme = "fino";
        plugins = [
          "git"
          "colorize"
          "screen"
          "tmux"
          "docker"
          "docker-compose"
          "podman"
          "python"
          "poetry"
          "pipenv"
          "pre-commit"
          "grc"
          "sudo"
          "rust"
          "deno"
          "bun"
          "volta"
          "node"
          "npm"
          "yarn"
          "mvn"
          "vscode"
          "battery"
          "eza"
          "fzf"
          "zoxide"
          "themes"
        ]
        ++ lib.optionals pkgs.stdenv.isLinux (
          [ "systemd" ]
          ++ lib.optionals (distroId == distroIds.fedora || distroId == distroIds.almalinux) [
            "dnf"
            "firewalld"
          ]
          ++ lib.optionals (distroId == distroIds.ubuntu) [
            "ubuntu"
            "ufw"
          ]
          ++ lib.optionals (distroId == distroIds.debian) [ "debian" ]
        )
        ++ lib.optionals pkgs.stdenv.isDarwin [
          "macos"
          "iterm2"
          "brew"
          "xcode"
        ];
      };
      initContent = ''
        ${lib.optionalString pkgs.stdenv.isDarwin ''
          zstyle :omz:plugins:iterm2 shell-integration yes
        ''}

        export EDITOR="vi"
        if [[ -z "$SSH_CONNECTION" ]] && command -v code >/dev/null 2>&1; then
          export EDITOR="code --wait"
        fi

        if [[ -f "$HOME/.secrets" ]]; then
          if [[ -z "$(find "$HOME/.secrets" -perm 600)" ]]; then
            echo "WARNING: Permissions for $HOME/.secrets are insecure! Please run: chmod 600 $HOME/.secrets"
          fi
          source "$HOME/.secrets"
        fi

        [[ -f "$DVM_DIR/dvm.sh" ]] && . "$DVM_DIR/dvm.sh"
        [[ -f "$DVM_DIR/bash_completion" ]] && . "$DVM_DIR/bash_completion"
      '';

      envExtra = ''
        [[ -f "$HOME/.cargo/env" ]] && . "$HOME/.cargo/env"
      '';

      profileExtra = ''
        typeset -U path

        path=(
          "$HOME/bin"
          "$HOME/.local/bin"
          "$HOME/.volta/bin"
          $path
        )

        export PATH
        export VOLTA_HOME="$HOME/.volta"
        export VOLTA_FEATURE_PNPM=1
      '';
    };
  };
}
