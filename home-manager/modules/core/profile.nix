{
  config,
  lib,
  ...
}:

let
  cfg = config.modules.core.profile;
  constants = config.modules.core.constants;

  desktopModules = {
    shell = {
      direnv = true;
      eza = true;
      fd = true;
      fzf = true;
      ripgrep = true;
      zoxide = true;
      zsh = true;
    };

    development = {
      agentDeck = true;
      agtx = true;
      aoe = true;
      bun = true;
      claudeCode = true;
      gh = true;
      git = true;
      lazygit = true;
      opencode = {
        enable = true;
        enableDesktop = true;
      };
      openclaw = false;
      openspec = true;
      pi = true;
      qmd = true;
    };

    programs = {
      alacritty = true;
      btop = true;
      ghostty = true;
      glow = true;
      himalaya = true;
      lazydocker = true;
      ssh = true;
      syncthing = true;
      tmux = true;
      zellij = true;
    };

    editors = {
      neovim = {
        enable = true;
        plugins = {
          opencode = true;
        };
      };
      vim = true;
    };
  };

  serverModules = {
    shell = {
      direnv = false;
      eza = false;
      fd = true;
      fzf = true;
      ripgrep = true;
      zoxide = false;
      zsh = true;
    };

    development = {
      agentDeck = false;
      agtx = false;
      aoe = false;
      bun = false;
      claudeCode = false;
      gh = false;
      git = true;
      lazygit = true;
      opencode = {
        enable = false;
        enableDesktop = false;
      };
      openclaw = false;
      openspec = false;
      pi = false;
      qmd = false;
    };

    programs = {
      alacritty = false;
      btop = true;
      ghostty = false;
      glow = true;
      himalaya = false;
      lazydocker = true;
      ssh = true;
      syncthing = false;
      tmux = true;
      zellij = false;
    };

    editors = {
      neovim = {
        enable = false;
        plugins = {
          opencode = false;
        };
      };
      vim = true;
    };
  };

  profileModules = {
    ${constants.profiles.desktop} = desktopModules;
    ${constants.profiles.server} = serverModules;
  };

in
{
  options.modules.core.profile = {
    name = lib.mkOption {
      type = lib.types.enum (builtins.attrValues constants.profiles);
      default = constants.profiles.desktop;
      description = "Profile name";
    };

    modules = lib.mkOption {
      type = lib.types.submodule {
        options = {
          shell = lib.mkOption {
            type = lib.types.attrsOf lib.types.bool;
            description = "Shell module enable flags";
          };
          development = lib.mkOption {
            type = lib.types.attrsOf (
              lib.types.oneOf [
                lib.types.bool
                (lib.types.submodule {
                  options = {
                    enable = lib.mkOption {
                      type = lib.types.bool;
                      description = "Whether to enable this development module";
                    };
                    enableDesktop = lib.mkOption {
                      type = lib.types.bool;
                      description = "Whether to enable the desktop variant";
                    };
                  };
                })
              ]
            );
            description = "Development module enable flags (bool or { enable, enableDesktop })";
          };
          programs = lib.mkOption {
            type = lib.types.attrsOf lib.types.bool;
            description = "Program module enable flags";
          };
          editors = lib.mkOption {
            type = lib.types.attrsOf (
              lib.types.oneOf [
                lib.types.bool
                (lib.types.submodule {
                  options = {
                    enable = lib.mkOption {
                      type = lib.types.bool;
                      description = "Whether to enable this editor module";
                    };
                    plugins = lib.mkOption {
                      type = lib.types.attrsOf lib.types.bool;
                      description = "Plugin enable flags for this editor";
                    };
                  };
                })
              ]
            );
            description = "Editor module enable flags (bool or { enable, plugins })";
          };
        };
      };
      readOnly = true;
      description = "Modules enabled for the profile";
    };
  };

  config.modules.core.profile.modules =
    if builtins.hasAttr cfg.name profileModules then
      builtins.getAttr cfg.name profileModules
    else
      throw "core.profile: unknown profile '${cfg.name}'";
}
