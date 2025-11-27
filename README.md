# Home Manager Configuration

Nix flakes configuration for Generic Linux and macOS.

## Installation

```bash
git clone <repository-url> ~/.nix
cd ~/.nix

# Bootstrap with personal profile (default)
nix run home-manager -- switch --flake . -b backup

# Or with work profile
nix run home-manager -- switch --flake . -b backup --specialisation work
```

Restart your shell after installation.

## Usage

```bash
# Apply changes
hm

# Switch profiles
hmw  # work profile
hmp  # personal profile

# Update flake inputs
nix flake update

# Clean old generations
nh clean all --keep 3
```
