{ config, lib, ... }:

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
      bun = true;
      gh = true;
      git = true;
      lazygit = true;
      opencode = {
        enable = true;
        enableDesktop = false;
      };
      openspec = true;
    };

    programs = {
      alacritty = true;
      btop = true;
      ghostty = true;
      glow = true;
      himalaya = true;
      lazydocker = true;
      ssh = true;
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
      bun = false;
      gh = false;
      git = true;
      lazygit = true;
      opencode = {
        enable = false;
        enableDesktop = false;
      };
      openspec = false;
    };

    programs = {
      alacritty = false;
      btop = true;
      ghostty = false;
      glow = true;
      himalaya = false;
      lazydocker = true;
      ssh = true;
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
      description = "Profile name.";
    };

    modules = lib.mkOption {
      type = lib.types.attrsOf (lib.types.attrsOf lib.types.anything);
      readOnly = true;
      description = "Modules enabled for the profile.";
    };
  };

  config.modules.core.profile.modules =
    if builtins.hasAttr cfg.name profileModules then
      builtins.getAttr cfg.name profileModules
    else
      throw "core.profile: unknown profile '${cfg.name}'";
}
