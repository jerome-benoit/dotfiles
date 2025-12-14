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
  profileModules = config.modules.core.profile.modules;
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
        NH_FLAKE = "$HOME/.nix";
        WORKSPACE = "$HOME/tmp";
        EDITOR = "vi";
      };
      shellAliases = {
        hm = lib.mkDefault "nh home switch --impure";
      };
      oh-my-zsh = {
        enable = true;
        theme = "fino";
        plugins = [
          "colorize"
          "screen"
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
          "volta"
          "node"
          "npm"
          "yarn"
          "mvn"
          "vscode"
          "battery"
          "themes"
        ]
        ++ lib.optional profileModules.development.git "git"
        ++ lib.optional profileModules.development.gh "gh"
        ++ lib.optional profileModules.development.bun "bun"
        ++ lib.optional profileModules.shell.direnv "direnv"
        ++ lib.optional profileModules.shell.eza "eza"
        ++ lib.optional profileModules.shell.fzf "fzf"
        ++ lib.optional profileModules.shell.zoxide "zoxide"
        ++ lib.optional profileModules.programs.tmux "tmux"
        ++ lib.optional pkgs.stdenv.isLinux "systemd"
        ++ lib.optionals (distroId == distroIds.fedora || distroId == distroIds.almalinux) [
          "dnf"
          "firewalld"
        ]
        ++ lib.optionals (distroId == distroIds.ubuntu) [
          "ubuntu"
          "ufw"
        ]
        ++ lib.optional (distroId == distroIds.debian) "debian"
        ++ lib.optionals pkgs.stdenv.isDarwin [
          "macos"
          "iterm2"
          "brew"
          "pod"
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

        export DVM_DIR="$HOME/.dvm"
        [[ -f "$DVM_DIR/dvm.sh" ]] && source "$DVM_DIR/dvm.sh"
        [[ -f "$DVM_DIR/bash_completion" ]] && source "$DVM_DIR/bash_completion"

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
