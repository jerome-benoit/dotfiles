# Task Completion Checklist

## Before Committing Any Changes

### 0. Decrypt Private Configuration (if needed for evaluation)

```bash
make decrypt-private  # Required for impure Nix evaluation
```

Skip decryption for pure checks, which use placeholder private configuration.
See `suggested_commands`, **Pure and private evaluation**, for the distinction.

### 1. Format Code

```bash
nix fmt
```

### 2. Run All Checks

```bash
nix flake check
```

This validates:

- [ ] All .nix files are properly formatted
- [ ] No broken symlinks in build output
- [ ] statix lint passes without warnings (fix findings; do not suppress rules in statix.toml)
- [ ] deadnix passes (no dead code)
- [ ] Home configurations for the current platform build successfully (personal/almalinux on Linux, work on macOS)
- [ ] Relevant integration checks pass (see `suggested_commands`, **Validation & Testing**)

### 3. Test Changes Locally

```bash
hm                    # Apply changes (from within a specialisation)
# or
make switch SPEC=work # Apply with explicit specialisation
```

### 4. Clean Secrets

```bash
make clean            # Remove decrypted plaintext from disk
```

## Code Quality Checklist

- [ ] Follow module structure pattern (options + config with mkIf)
- [ ] Use appropriate lib functions (mkIf, mkDefault, mkForce, mkMerge)
- [ ] Add assertions for module dependencies
- [ ] Add warnings for non-fatal issues
- [ ] Respect 2-space indentation
- [ ] Keep lines under 100 characters
- [ ] Ensure final newline in files
- [ ] No trailing whitespace (except markdown)

## Adding New Modules

1. **Create module file** in appropriate category:

   ```
   home-manager/modules/<category>/<name>.nix
   ```

2. **Follow standard structure**:

   ```nix
   { config, lib, pkgs, ... }:
   let
     cfg = config.modules.<category>.<name>;
   in
   {
     options.modules.<category>.<name> = {
       enable = lib.mkEnableOption "<name> configuration";
     };

     config = lib.mkIf cfg.enable {
       # Configuration here
     };
   }
   ```

3. **Add import** to category's `default.nix`:

   ```nix
   imports = [
     # ... existing imports
     ./<name>.nix
   ];
   ```

4. **Add to profile.nix** (both desktop and server):

   ```nix
   desktopModules = {
     <category> = {
       # ... existing
       <name> = true;  # or false for server
     };
   };
   ```

5. **Wire up in home.nix**:

   ```nix
   modules.<category> = {
     # ... existing
     <name>.enable = profileModules.<category>.<name>;
   };
   ```

6. **Run checks**:
   ```bash
   nix flake check
   ```

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
