# Task Completion Checklist

## Before Committing Any Changes

### 0. Choose an Evaluation Mode

Pure Nix checks use placeholder private configuration and need no decryption.
Use `make decrypt-private` only when inspecting the real configuration with raw
`--impure` Nix commands. See `suggested_commands`, **Pure and private evaluation**.

For normal local builds and switches, let the wrapper decrypt private
configuration. `make build`, `make switch`, and `hm` refuse to run if
`secrets/private.dec.json` already exists. After manual inspection, re-encrypt
any edits you intend to keep, then run `make clean` before using these commands.

### 1. Format Code

```bash
nix fmt
```

### 2. Run All Checks

```bash
nix flake check --no-build  # Evaluate flake outputs without building the checks
nix flake check             # Evaluate and build checks for the current platform
```

The build step validates:

- [ ] All .nix files are properly formatted
- [ ] No broken symlinks in build output
- [ ] statix lint passes without warnings (fix findings; do not suppress rules in statix.toml)
- [ ] deadnix passes (no dead code)
- [ ] Home configurations for the current platform build successfully (personal/almalinux on Linux, work on macOS)
- [ ] Relevant integration checks pass (see `suggested_commands`, **Validation & Testing**)

### 3. Test Changes Locally

Use `make build` to build your actual Home Manager configuration without
activating it. To apply it:

```bash
hm                    # Apply changes (from within a specialisation)
# or
make switch SPEC=work # Apply with explicit specialisation
```

### 4. Clean Secrets

```bash
make clean            # Remove decrypted files and temporary artifacts directly under secrets/
```

For editor workspaces left after an uncatchable interruption, see
[Private configuration and credentials](../../README.md#private-configuration-and-credentials).

## Code Quality Checklist

- [ ] For modules with an `enable` option, follow [Nix Module Structure](code_style_conventions.md#nix-module-structure)
- [ ] Use appropriate lib functions (mkIf, mkDefault, mkForce, mkMerge)
- [ ] Add assertions for module dependencies
- [ ] Add warnings for non-fatal issues
- [ ] Respect 2-space indentation
- [ ] Keep lines under 100 characters
- [ ] Ensure final newline in files
- [ ] No trailing whitespace (except markdown)

## Adding New Modules

1. Create `home-manager/modules/<category>/<name>.nix`. If the module has an
   `enable` option, follow [Nix Module Structure](code_style_conventions.md#nix-module-structure).
2. Add the module to the category's `default.nix`. See
   [Import Pattern](code_style_conventions.md#import-pattern).
3. If a profile controls the module, add its defaults in
   `home-manager/modules/core/profile.nix` and wire them in `home-manager/home.nix`.
   See [Profile System](code_style_conventions.md#profile-system).
4. Run `nix flake check`.

## Adding New Themes

Add a `mkTheme` entry to the `imports` list in `home-manager/modules/themes/default.nix`. Start with a supported family and variant. This example uses the existing Tokyo Night Storm integrations with a separate registry key and an editable palette:

```nix
(mkTheme "myTokyoNightStorm" {
  family = "tokyonight";
  name = "tokyo-night-storm";
  altName = "TokyoNight Storm";
  fileName = "tokyo_night_storm";
  neovimName = "tokyonight-storm";
  style = "storm";
  colors = {
    bg = "#24283b";
    fg = "#a9b1d6";
    black = "#414868";
    red = "#f7768e";
    green = "#73daca";
    yellow = "#e0af68";
    blue = "#7aa2f7";
    magenta = "#bb9af7";
    cyan = "#7dcfff";
    white = "#8089b3";
    brightWhite = "#a9b1d6";
  };
})
```

Every color must use `#RRGGBB`. Omitted `bright*` colors default to the corresponding base color. Palette consumers use these colors; applications that select a built-in theme retain that theme's own palette.

Select the key with `modules.themes.active = "myTokyoNightStorm";` in the Home Manager configuration. Work and personal specialisations force their own active key; update the corresponding `theme` argument in `core/specialisations.nix` when selecting the new entry for those contexts.

A new family also requires consumer support: extend Neovim's plugin and setup tables, tmux's plugin table and the applicable application mappings. Use identifiers actually provided by each application's selected theme package.

## Platform-Specific Changes

See `code_style_conventions` memory for platform-specific code patterns.

Exercise activation and login on each affected native platform when changing
service startup or secret ordering. Synthetic ordering checks do not prove native
service readiness at login.

## Updating Dependencies

See `suggested_commands` memory for dependency management commands.

## Adding New Users

1. **Add homeConfiguration** in `flake.nix`:

   ```nix
   homeConfigurations = {
     # ... existing
     "newuser" = mkHomeConfiguration {
       arch = constants.systems.linux.arch;  # or darwin
       profile = constants.profiles.desktop;  # or server
       username = "newuser";
     };
   };
   ```

2. **Add check** in flake checks section if needed

3. **Update CI** if the user should be tested

## CI/CD & Debugging

See `suggested_commands` memory for CI details, debugging tips, and operational commands.
