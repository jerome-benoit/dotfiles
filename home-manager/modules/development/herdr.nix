{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.development.herdr;
  system = pkgs.stdenv.hostPlatform.system;
  theme = config.modules.themes.current;

  supportedPackage =
    package:
    if package != null && lib.meta.availableOn pkgs.stdenv.hostPlatform package then package else null;

  mkDesktopPackage =
    let
      package = supportedPackage (pkgs.herdr-desktop or null);
    in
    if cfg.corePackage != null && package != null then
      (package.override { herdr-core = cfg.corePackage; }).overrideAttrs (
        previousAttrs:
        lib.optionalAttrs pkgs.stdenv.hostPlatform.isDarwin {
          # Workaround: Nix-managed apps must not rewrite user CLI launchers.
          # Remove when nixpkgs disables automatic CLI link installation.
          patches = (previousAttrs.patches or [ ]) ++ [
            ../../../patches/herdr-desktop-nix-cli-link.patch
          ];
        }
      )
    else
      null;

  # Herdr's built-in themes (src/app/state.rs THEME_NAMES).
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

  # Shared theme family.style -> Herdr theme (Herdr has no storm/macchiato/frappe
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

  optionalPackages = config.modules.core.lib.mkOptionalPackages [
    {
      package = cfg.package;
      warning = "herdr: package not available for system ${system}";
    }
    {
      package = cfg.corePackage;
      warning = "herdr: core package not available for system ${system}";
    }
    {
      package = cfg.desktopPackage;
      enabled = cfg.enableDesktop;
      warning = "herdr: Desktop package not available for system ${system}";
    }
  ];
in
{
  options.modules.development.herdr = {
    enable = lib.mkEnableOption "Herdr configuration";

    enableDesktop = lib.mkEnableOption "Herdr Desktop integration";

    package = config.modules.core.lib.mkOptionalPackageOption {
      default = supportedPackage (pkgs.herdr or null);
      defaultText = lib.literalExpression "pkgs.herdr or null";
      description = "Herdr terminal UI package";
      example = lib.literalExpression "pkgs.herdr";
    };

    corePackage = config.modules.core.lib.mkOptionalPackageOption {
      default = supportedPackage (pkgs.herdr-core or null);
      defaultText = lib.literalExpression "pkgs.herdr-core or null";
      description = "Herdr terminal engine and hc CLI package. null omits the packaged engine.";
      example = lib.literalExpression "pkgs.herdr-core";
    };

    desktopPackage = config.modules.core.lib.mkOptionalPackageOption {
      default = null;
      defaultText = lib.literalExpression "null";
      description = "Herdr Desktop package. The default uses corePackage as its fallback engine.";
    };

    theme = lib.mkOption {
      type = lib.types.nullOr (lib.types.enum herdrThemeNames);
      default = null;
      description = "Initial built-in Herdr theme; null seeds the shared theme (modules.themes.current). Existing config.toml files are preserved.";
      example = "tokyo-night";
    };
  };

  config = lib.mkIf cfg.enable {
    modules.development.herdr.desktopPackage = lib.mkIf cfg.enableDesktop (
      lib.mkDefault mkDesktopPackage
    );

    assertions = [
      {
        assertion = !cfg.enableDesktop || cfg.desktopPackage == null || cfg.corePackage != null;
        message = "herdr: Desktop requires a non-null corePackage.";
      }
    ];

    home.packages = optionalPackages.packages;

    warnings = optionalPackages.warnings;

    # Seed once; never overwrite the user's edits.
    home.activation.herdrConfig = lib.mkIf (cfg.package != null) (
      let
        # Herdr uses ~/.config/herdr on Linux and macOS (no platform dir).
        configDir = "${config.xdg.configHome}/herdr";
        configFile = "${configDir}/config.toml";
      in
      lib.hm.dag.entryAfter [ "writeBoundary" ] ''
        run mkdir -p "${configDir}"
        if [[ ! -f "${configFile}" ]]; then
          run ${lib.getExe pkgs.bash} -c 'cat > "$1"' -- "${configFile}" << 'EOF'
        ${lib.removeSuffix "\n" herdrConfig}
        EOF
        fi
      ''
    );
  };
}
