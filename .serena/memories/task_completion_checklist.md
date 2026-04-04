# Task Completion Checklist

## Before Committing Any Changes

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
- [ ] statix lint passes (configured via statix.toml)
- [ ] deadnix passes (no dead code)
- [ ] All home configurations build successfully (fraggle, almalinux, I339261)

### 3. Test Changes Locally

```bash
hm  # Apply changes with home-manager
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

Add a new `mkTheme` call in `home-manager/modules/themes/default.nix`:

```nix
(mkTheme "myThemeKey" {
  family = "mytheme";
  name = "my-theme";
  altName = "My Theme";
  fileName = "my_theme";
  style = "dark";
  colors = {
    bg = "#..."; fg = "#...";
    black = "#..."; red = "#..."; green = "#..."; yellow = "#...";
    blue = "#..."; magenta = "#..."; cyan = "#..."; white = "#...";
    brightBlack = "#..."; brightRed = "#..."; brightGreen = "#..."; brightYellow = "#...";
    brightBlue = "#..."; brightMagenta = "#..."; brightCyan = "#..."; brightWhite = "#...";
  };
})
```

Then set `config.modules.themes.active = "myThemeKey"` to use it.

## Platform-Specific Changes

See `code_style_conventions` memory for platform-specific code patterns.

## Updating Dependencies

See `suggested_commands` memory for dependency management commands.

## Adding New Users

1. **Add homeConfiguration** in `flake.nix`:

   ```nix
   homeConfigurations = {
     # ... existing
     "newuser" = mkHomeConfiguration {
       arch = constants.systems.linux.arch;  # or darwin
       username = "newuser";
     };
   };
   ```

2. **Add check** in flake checks section if needed

3. **Update CI** if the user should be tested

## CI/CD & Debugging

See `suggested_commands` memory for CI details, debugging tips, and operational commands.
