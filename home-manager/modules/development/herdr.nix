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

  # herdr's built-in themes (src/app/state.rs THEME_NAMES).
  herdrThemeNames = [
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
  ];

  # Shared theme family.style -> herdr theme (herdr has no storm/macchiato/frappe
  # variants; extend when adding a theme to modules/themes).
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
      herdrThemeByFamily.${theme.family}.${theme.style}
        or (if lib.elem theme.family herdrThemeNames then theme.family else "catppuccin");

  herdrConfig = ''
    # Edit in-app (prefix+s) or run `herdr server reload-config` after changes.
    # Full default config: herdr --default-config

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
      defaultText = lib.literalExpression "inputs.herdr.packages.\${system}.default or .herdr or null";
      description = "Herdr package";
      example = lib.literalExpression "inputs.herdr.packages.\${system}.default";
    };

    theme = lib.mkOption {
      type = lib.types.nullOr (lib.types.enum herdrThemeNames);
      default = null;
      description = "Built-in herdr theme. null follows the shared theme system (modules.themes.current).";
      example = "tokyo-night";
    };
  };

  config = lib.mkIf cfg.enable {
    home.packages = lib.optional (cfg.package != null) cfg.package;

    warnings = lib.optional (cfg.package == null) "herdr: package not available for system ${system}";

    # Seed once; never overwrite the user's edits.
    home.activation.herdrConfig = lib.mkIf (cfg.package != null) (
      let
        # herdr uses ~/.config/herdr on Linux and macOS (no platform dir).
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
