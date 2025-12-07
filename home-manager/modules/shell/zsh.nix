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
  systemZsh = pkgs.runCommand "zsh-system" { meta.mainProgram = "zsh"; } "mkdir -p $out";
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
        NH_FLAKE = lib.mkDefault "$HOME/.nix";
        DVM_DIR = lib.mkDefault "$HOME/.dvm";
        WORKSPACE = lib.mkDefault "$HOME/tmp";
        EDITOR = lib.mkDefault "vi";
      };
      shellAliases = {
        hm = lib.mkDefault "nh home switch --impure";
      };
      oh-my-zsh = {
        enable = true;
        theme = "fino";
        plugins = [
          "git"
          "gh"
          "colorize"
          "direnv"
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

        if [[ -z "$SSH_CONNECTION" ]] && command -v code >/dev/null 2>&1; then
          ${
            if pkgs.stdenv.isDarwin then
              ''
                export EDITOR="code --wait"
              ''
            else if pkgs.stdenv.isLinux then
              ''
                if [[ -n "$DISPLAY" || -n "$WAYLAND_DISPLAY" ]]; then
                  export EDITOR="code --wait"
                fi
              ''
            else
              ""
          }
        fi

        if [[ -f "$HOME/.secrets" ]]; then
          if [[ -z "$(find "$HOME/.secrets" -perm 600)" ]]; then
            echo "\033[1;31mWARNING: $HOME/.secrets has insecure permissions!\033[0m"
            echo "Please run: chmod 600 $HOME/.secrets"
          else
            source "$HOME/.secrets"
          fi
        fi
      '';

      envExtra = ''
        [[ -f "$HOME/.cargo/env" ]] && . "$HOME/.cargo/env"
      '';

      profileExtra = ''
        typeset -U path

        export VOLTA_HOME="$HOME/.volta"
        export VOLTA_FEATURE_PNPM=1

        path=(
          "$HOME/bin"
          "$HOME/.local/bin"
          "$VOLTA_HOME/bin"
          $path
        )

        export PATH

        [[ -f "$DVM_DIR/dvm.sh" ]] && . "$DVM_DIR/dvm.sh"
        [[ -f "$DVM_DIR/bash_completion" ]] && . "$DVM_DIR/bash_completion"

        # Glob qualifiers: (N)=null glob, (-)=no symlinks, (.)=regular files, (:o)=sorted
        if [[ -d "$HOME/.zprofile.d" ]]; then
          for profile_script in "$HOME/.zprofile.d"/*.zsh(N-.:o); do
            [[ -r "$profile_script" ]] && source "$profile_script"
          done
          unset profile_script
        fi
      '';
    };
  };
}
