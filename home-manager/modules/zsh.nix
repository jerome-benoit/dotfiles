{ pkgs, ... }:

let
  systemZsh = pkgs.runCommand "zsh-system" { } "mkdir -p $out";
in
{
  programs.zsh = {
    enable = true;
    package = systemZsh;
    sessionVariables = {
      NH_FLAKE = "$HOME/.nix";
      DVM_DIR = "$HOME/.dvm";
    };
    shellAliases = {
      hm = "nh home switch";
      zed = "flatpak run dev.zed.Zed";
    };
    oh-my-zsh = {
      enable = true;
      theme = "fino";
      plugins = [
        "git"
        "dnf"
        "systemd"
        "screen"
        "firewalld"
        "tmux"
        "colorize"
        "podman"
        "docker"
        "docker-compose"
      ]
      ++ (if pkgs.stdenv.isDarwin then [ "brew" ] else [ ])
      ++ [
        "rust"
        "python"
        "poetry"
        "pre-commit"
        "sudo"
        "deno"
        "bun"
        "volta"
        "node"
        "npm"
        "yarn"
        "mvn"
        "vscode"
        "fzf"
        "zoxide"
        "themes"
      ];
    };
    initContent = ''
      if [ -f "$HOME/.secrets" ] && [ "$(stat -c "%a" "$HOME/.secrets")" != "600" ]; then
        echo "WARNING: Permissions for $HOME/.secrets are insecure! Please run: chmod 600 $HOME/.secrets"
      elif [ -f "$HOME/.secrets" ]; then
        source "$HOME/.secrets"
      fi

      [ -f "$DVM_DIR/dvm.sh" ] && . "$DVM_DIR/dvm.sh"
      [ -f "$DVM_DIR/bash_completion" ] && . "$DVM_DIR/bash_completion"
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
}
