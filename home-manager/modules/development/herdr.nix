{
  config,
  lib,
  pkgs,
  inputs,
  ...
}:

let
  cfg = config.modules.development.herdr;
  system = pkgs.stdenv.hostPlatform.system;
  theme = config.modules.themes.current;

  herdrPackages = inputs.herdr.packages.${system} or { };
  herdrPackage = herdrPackages.default or herdrPackages.herdr or null;

  # Map the shared theme system (family + style) onto herdr's built-in theme
  # identifiers. herdr ships no storm/macchiato/frappe variants, so those fall
  # back to their family's default dark theme.
  herdrThemeByFamily = {
    tokyonight = {
      night = "tokyo-night";
      storm = "tokyo-night";
      day = "tokyo-night-day";
    };
    catppuccin = {
      mocha = "catppuccin";
      macchiato = "catppuccin";
      frappe = "catppuccin";
      latte = "catppuccin-latte";
    };
  };

  resolvedTheme =
    if cfg.theme != null then
      cfg.theme
    else
      herdrThemeByFamily.${theme.family}.${theme.style} or "catppuccin";

  herdrConfig = ''
    # Herdr configuration — managed by home-manager (modules/development/herdr.nix)
    # herdr runs fine without a config; this seeds sensible defaults on first run.
    # Edit in-app (prefix+s) or run `herdr server reload-config` after changes.
    # Print the full commented default config with: herdr --default-config

    onboarding = false

    [theme]
    name = "${resolvedTheme}"
  '';
in
{
  options.modules.development.herdr = {
    enable = lib.mkEnableOption "herdr configuration";

    package = lib.mkOption {
      type = lib.types.nullOr lib.types.package;
      default = herdrPackage;
      defaultText = lib.literalExpression "inputs.herdr.packages.\${system}.default";
      description = "Herdr package";
      example = lib.literalExpression "inputs.herdr.packages.\${system}.default";
    };

    theme = lib.mkOption {
      type = lib.types.nullOr (
        lib.types.enum [
          "catppuccin"
          "catppuccin-latte"
          "terminal"
          "tokyo-night"
          "tokyo-night-day"
          "dracula"
          "nord"
          "gruvbox"
          "gruvbox-light"
          "one-dark"
          "one-light"
          "solarized"
          "solarized-light"
          "kanagawa"
          "kanagawa-lotus"
          "rose-pine"
          "rose-pine-dawn"
          "vesper"
        ]
      );
      default = null;
      description = "Built-in herdr theme. null follows the shared theme system (modules.themes.current).";
      example = "tokyo-night";
    };
  };

  config = lib.mkIf cfg.enable {
    home.packages = lib.optional (cfg.package != null) cfg.package;

    warnings = lib.optional (cfg.package == null) "herdr: package not available for system ${system}";

    # Seed once: herdr owns config.toml after first run (in-app prefix+s /
    # `herdr server reload-config`), so activation never overwrites it.
    home.activation.herdrConfig = lib.mkIf (cfg.package != null) (
      let
        # herdr config-dir precedence (herdr src/config/io.rs): $HERDR_CONFIG_PATH
        # (exact file) then $XDG_CONFIG_HOME/herdr, else $HOME/.config/herdr on both
        # Linux and macOS (herdr never uses the macOS platform dir). config.xdg.configHome
        # resolves to ~/.config here, matching herdr's fallback and sibling modules.
        configDir = "${config.xdg.configHome}/herdr";
        configFile = "${configDir}/config.toml";
      in
      lib.hm.dag.entryAfter [ "writeBoundary" ] ''
        run mkdir -p "${configDir}"
        if [[ ! -f "${configFile}" ]]; then
          run cat > "${configFile}" << 'EOF'
        ${lib.removeSuffix "\n" herdrConfig}
        EOF
        fi
      ''
    );
  };
}
