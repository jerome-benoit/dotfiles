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

1. **Create theme file**:

   ```
   home-manager/modules/themes/<theme-name>.nix
   ```

2. **Define theme structure**:

   ```nix
   { lib, ... }:
   {
     config.modules.themes.<themeCamelCase> = {
       name = "<theme-name>";
       altName = "<Theme Display Name>";
       fileName = "<theme_file_name>";
       colors = {
         bg = "#...";
         fg = "#...";
         # ... full palette
       };
     };
   }
   ```

3. **Add import** to `themes/default.nix`

4. **Reference in programs**:
   ```nix
   theme = config.modules.themes.<themeCamelCase>;
   # Use theme.colors.blue, theme.name, etc.
   ```

## Platform-Specific Changes

### Adding Linux-only Packages

```nix
home.packages = with pkgs; [
  # common packages
] ++ lib.optionals pkgs.stdenv.isLinux [
  # Linux-only packages
];
```

### Adding macOS-only Packages

```nix
home.packages = with pkgs; [
  # common packages
] ++ lib.optionals pkgs.stdenv.isDarwin [
  # macOS packages from nixpkgs
];
```

### Adding macOS Casks (Homebrew)

In `modules/core/packages.nix`:

```nix
home.file.".Brewfile" = lib.mkIf pkgs.stdenv.isDarwin {
  text = ''
    cask "app-name"
  '';
};
```

## Updating Dependencies

```bash
# Update all inputs
nix flake update

# Update specific input
nix flake lock --update-input nixpkgs
nix flake lock --update-input home-manager
nix flake lock --update-input opencode
nix flake lock --update-input opencode-nvim
```

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

## CI/CD Notes

The GitHub workflow (`.github/workflows/check.yml`) runs on:

- Push to `main` (paths: flake.\*, home-manager/**, checks/**, constants.nix)
- Pull requests to `main`
- Manual dispatch

Matrix:

- `ubuntu-latest` / `x86_64-linux`
- `macos-latest` / `aarch64-darwin`

## Debugging Tips

### Build specific configuration

```bash
nix build .#homeConfigurations.fraggle.activationPackage
```

### Check what would be installed

```bash
nix eval .#homeConfigurations.fraggle.config.home.packages --apply 'pkgs: map (p: p.name or p.pname or "unknown") pkgs'
```

### Interactive debugging

```bash
nix repl
:lf .
homeConfigurations.fraggle.config.modules.core.profile.name
```

### Check module option values

```bash
nix eval .#homeConfigurations.fraggle.config.modules.shell.zsh.enable
```
