{
  pkgs,
  home-manager,
  inputs,
}:
let
  # Workaround: upstream plugin outputs retain /usr/bin/env interpreters, absent
  # inside Nix sandboxes. Materialize the same sources with declared interpreters;
  # module ordering, plugin code and scheduler behavior stay unchanged.
  # Remove when nixpkgs patches the plugin script shebangs itself.
  sandboxPkgs = pkgs.extend (
    _final: previous: {
      tmuxPlugins = previous.lib.mapAttrs (
        _name: plugin:
        if previous.lib.isDerivation plugin then
          plugin.overrideAttrs (old: {
            buildInputs = (old.buildInputs or [ ]) ++ [ previous.bash ];
            postInstall = (old.postInstall or "") + ''
              patchShebangs --host "$out"
            '';
          })
        else
          plugin
      ) previous.tmuxPlugins;
    }
  );
  configuration = home-manager.lib.homeManagerConfiguration {
    pkgs = sandboxPkgs;
    extraSpecialArgs = { inherit inputs; };
    modules = [
      ../home-manager/modules/core/lib.nix
      ../home-manager/modules/themes/default.nix
      ../home-manager/modules/editors/neovim.nix
      ../home-manager/modules/development/opencode.nix
      ../home-manager/modules/programs/tmux.nix
      ../home-manager/modules/programs/zellij.nix
      ({ lib, ... }: {
        options.modules.core.constants.historySize = lib.mkOption {
          type = lib.types.int;
          default = 5000;
        };
      })
      {
        home = {
          username = "consumer-check";
          homeDirectory = "/home/consumer-check";
          stateVersion = "26.05";
        };
        modules = {
          editors.neovim = {
            enable = true;
            plugins.opencode.enable = true;
          };
          development.opencode = {
            enable = true;
            opencodePackage = null;
          };
          programs = {
            tmux.enable = true;
            zellij.enable = true;
          };
        };
      }
    ];
  };
  config = configuration.config;
  catppuccin =
    (configuration.extendModules {
      modules = [ { modules.themes.active = "catppuccinMocha"; } ];
    }).config;
  terminalFixtures = pkgs.writeText "consumer-terminal-fixtures.json" (
    builtins.toJSON {
      tmux =
        pkgs.writeText "consumer-catppuccin-tmux.conf"
          catppuccin.xdg.configFile."tmux/tmux.conf".text;
      tokyo = pkgs.writeText "consumer-tokyonight-tmux.conf" config.xdg.configFile."tmux/tmux.conf".text;
      zellij = config.programs.zellij.extraConfig;
    }
  );
  init = pkgs.writeText "consumer-init.lua" config.programs.neovim.initLua;
in
pkgs.runCommand "check-consumer-contracts"
  {
    nativeBuildInputs = [
      pkgs.python3
      pkgs.go
      pkgs.zsh
      pkgs.git
      pkgs.coreutils
    ]
    ++ pkgs.lib.optionals pkgs.stdenv.hostPlatform.isLinux [ (pkgs.lib.getBin pkgs.procps) ];
  }
  ''
    export HOME="$TMPDIR/home"
    export XDG_CONFIG_HOME="$HOME/.config"
    export XDG_DATA_HOME="$HOME/.local/share"
    export XDG_STATE_HOME="$HOME/.local/state"
    export XDG_CACHE_HOME="$HOME/.cache"
    mkdir -p "$HOME" "$XDG_CACHE_HOME"
    mkdir -p "$XDG_DATA_HOME/nvim/site/pack"
    ln -s ${config.xdg.dataFile."nvim/site/pack/hm".source} "$XDG_DATA_HOME/nvim/site/pack/hm"
    ${pkgs.python3}/bin/python ${./consumer-shells.py} ${../.} ${pkgs.lazygit.src} \
      ${pkgs.go}/bin/go ${pkgs.zsh}/bin/zsh ${pkgs.bash}/bin/bash ${pkgs.git}/bin/git
    ${pkgs.python3}/bin/python ${./consumer-terminals.py} ${terminalFixtures} \
      ${pkgs.tmux}/bin/tmux ${pkgs.zellij}/bin/zellij
    export CONSUMER_SELECTOR=${../home-manager/modules/editors/treesitter-selection.lua}
    ${config.programs.neovim.finalPackage}/bin/nvim --headless -u ${init} -i NONE -n "$TMPDIR/start.txt" \
      -c 'lua vim.schedule(function() dofile("${./consumer-editors.lua}") end)'
    touch "$out"
  ''
