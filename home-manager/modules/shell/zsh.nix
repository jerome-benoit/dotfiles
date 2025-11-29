{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.shell.zsh;
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
        EDITOR = ''$(if [[ -n "$SSH_CONNECTION" ]]; then echo "vi"; else echo "code --wait"; fi)'';
      };
      shellAliases = {
        hm = "nh home switch";
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
        ++ lib.optionals pkgs.stdenv.isLinux [
          "dnf"
          "systemd"
          "firewalld"
        ]
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
        . "$HOME/.cargo/env"
      '';

      profileExtra = ''
        # prepend ~/.local/bin and ~/bin to $PATH unless it is already there
        if ! [[ "$PATH" =~ "$HOME/bin" ]]; then
            PATH="$HOME/bin:$PATH"
        fi
        if ! [[ "$PATH" =~ "$HOME/.local/bin:" ]]; then
            PATH="$HOME/.local/bin:$PATH"
        fi
        export PATH

        export VOLTA_HOME="$HOME/.volta"
        export VOLTA_FEATURE_PNPM=1
        if ! [[ "$PATH" =~ "$VOLTA_HOME/bin:" ]]; then
            export PATH="$VOLTA_HOME/bin:$PATH"
        fi
      '';
    };
  };
}
