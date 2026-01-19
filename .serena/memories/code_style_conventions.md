# Code Style and Conventions

## File Formatting (.editorconfig)

### Nix Files (*.nix)
- **Indent**: 2 spaces
- **Max line length**: 100 characters
- **Charset**: UTF-8
- **Line endings**: LF
- **Final newline**: Required
- **Trailing whitespace**: Trimmed

### Other Files
| Type | Indent | Notes |
|------|--------|-------|
| YAML (*.yml, *.yaml) | 2 spaces | |
| JSON (*.json) | 2 spaces | |
| Markdown (*.md) | - | No trailing whitespace trim, no max line |
| Lock files (*.lock) | - | No modifications |

## Nix Module Structure

Every module follows this pattern:

```nix
{ config, lib, pkgs, ... }:

let
  cfg = config.modules.<category>.<name>;
  # Optional: theme, constants, other config references
in
{
  options.modules.<category>.<name> = {
    enable = lib.mkEnableOption "<name> configuration";
    # Additional options if needed
  };

  config = lib.mkIf cfg.enable {
    # Assertions (optional)
    assertions = [
      {
        assertion = <condition>;
        message = "<module>: <error message>";
      }
    ];

    # Warnings (optional)
    warnings = lib.optional <condition> "<warning message>";

    # Actual configuration
    programs.<name> = {
      enable = true;
      # ...
    };
  };
}
```

## Naming Conventions

| Element | Convention | Example |
|---------|------------|---------|
| Module paths | `modules.<category>.<name>` | `modules.shell.zsh` |
| Option names | camelCase | `enableDesktop`, `shellAliases` |
| File names | lowercase, hyphens | `home-manager.nix`, `tokyo-night-storm.nix` |
| Theme attribute | camelCase | `tokyoNightStorm` |
| Constants | camelCase | `historySize`, `workEmail` |

## Import Pattern

Each category has a `default.nix` that imports all modules:

```nix
{
  imports = [
    ./module1.nix
    ./module2.nix
  ];
}
```

Main `modules/default.nix` imports category directories:

```nix
{
  imports = [
    ./core
    ./development
    ./editors
    ./programs
    ./shell
    ./themes
  ];
}
```

## Constants Access

### Root constants (flake-level)
Passed via `extraSpecialArgs` in flake.nix:
```nix
constants.systems.linux.arch  # "x86_64-linux"
constants.profiles.desktop    # "desktop"
constants.distros.fedora      # "fedora"
```

### Module constants (user-level)
Defined in `modules/core/constants.nix`:
```nix
config.modules.core.constants.username      # "Jérôme Benoit"
config.modules.core.constants.email         # "jerome.benoit@piment-noir.org"
config.modules.core.constants.workEmail     # "jerome.benoit@sap.com"
config.modules.core.constants.gpg.keyId     # "27B535D3"
config.modules.core.constants.historySize   # 50000
config.modules.core.constants.timezone      # "Europe/Paris"
config.modules.core.constants.hosts.rigel   # "rigel"
```

## Profile System

Access profile-enabled modules:
```nix
profileModules = config.modules.core.profile.modules;

# Check if module should be enabled
profileModules.shell.zsh        # true/false
profileModules.development.git  # true/false
profileModules.programs.tmux    # true/false

# Nested options
profileModules.development.opencode.enable
profileModules.editors.neovim.plugins.opencode
```

## Distro Detection

Access detected distro:
```nix
distroId = config.modules.core.distro.id;      # "fedora", "ubuntu", etc. or null
distroIds = config.modules.core.distro.ids;    # { fedora = "fedora"; ... }

# Usage in conditions
lib.optionals (distroId == distroIds.fedora) [ ... ]
```

## Theme System

Access theme colors:
```nix
theme = config.modules.themes.tokyoNightStorm;

theme.name       # "tokyo-night-storm"
theme.altName    # "TokyoNight Storm"
theme.fileName   # "tokyo_night_storm"
theme.colors.bg  # "#24283b"
theme.colors.fg  # "#a9b1d6"
theme.colors.blue # "#7aa2f7"
# ... (see tokyo-night-storm.nix for full palette)
```

## Platform-Specific Code

### Package selection
```nix
# Use system binary on Linux, Nix package on macOS
package = if pkgs.stdenv.isDarwin then pkgs.fzf else systemFzf;

# Create dummy package for system binary
systemFzf = pkgs.runCommand "fzf-system" {
  version = "0.60.0";  # Optional: for version checks
  meta.mainProgram = "fzf";
} "mkdir -p $out";
```

### Conditional configuration
```nix
# Platform-specific packages
lib.optionals pkgs.stdenv.isLinux [ pkgs.delta pkgs.grc ]
lib.optionals pkgs.stdenv.isDarwin [ pkgs.vscode pkgs.firefox ]

# Platform-specific settings
lib.mkIf pkgs.stdenv.isDarwin {
  settings.credential.helper = "osxkeychain";
}

# Merge platform-specific configs
programs.git = lib.mkMerge [
  { /* common config */ }
  (lib.mkIf pkgs.stdenv.isDarwin { /* macOS config */ })
];
```

## Assertions Pattern

Validate module dependencies:
```nix
assertions = [
  {
    assertion = config.modules.development.git.enable;
    message = "lazygit: Git module must be enabled (modules.development.git.enable = true)";
  }
  {
    assertion = config.modules.shell.fd.enable;
    message = "fzf: fd module must be enabled (modules.shell.fd.enable = true)";
  }
];
```

## Warnings Pattern

Emit warnings for non-fatal issues:
```nix
warnings =
  lib.optional (cfg.opencodePackage == null)
    "opencode: TUI and CLI package not available for system ${system}";
```

## Lib Functions Reference

| Function | Usage |
|----------|-------|
| `lib.mkIf` | Conditional config block |
| `lib.mkMerge` | Merge multiple configs |
| `lib.mkDefault` | Set overridable default |
| `lib.mkForce` | Force override value |
| `lib.mkEnableOption` | Create `enable` option |
| `lib.mkOption` | Create custom option |
| `lib.optional` | Single item if condition true |
| `lib.optionals` | List if condition true |
| `lib.optionalString` | String if condition true |
| `lib.optionalAttrs` | Attrs if condition true |
| `lib.hm.dag.entryAfter` | Home Manager activation ordering |

## Specialisation Overrides

Override settings per specialisation:
```nix
specialisation.work.configuration = {
  programs.ssh.matchBlocks."*.local" = {
    user = "fraggle";
  };
};
```
