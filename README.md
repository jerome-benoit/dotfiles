# Home Manager Configuration

Nix flakes configuration for Generic Linux and macOS.

## Installation

```bash
git clone <repository-url> ~/.nix
cd ~/.nix

# Bootstrap with default, personal, or work profile
nix run home-manager -- switch --flake . --impure -b backup [--specialisation personal|work]
```

Restart your shell.

## Usage

### Home Manager

```bash
# Apply changes (preserves current profile)
hm

# Switch profiles (available only from personal or work)
hmw  # work
hmp  # personal
```

### Formatting

```bash
nix fmt              # Format all .nix files
nix fmt file.nix     # Format specific file
```

### Validation

```bash
nix flake check      # Run all checks:
                     # - Formatting verification
                     # - Symlinks validation
                     # - Build all home-manager configurations
```

### Maintenance

```bash
nix flake update     # Update inputs
nh clean all --keep 3
```
