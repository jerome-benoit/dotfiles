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

```bash
# Apply changes (preserves current profile)
hm

# Switch profiles (available only from personal or work)
hmw  # work
hmp  # personal

# Update flake inputs
nix flake update

# Clean old generations
nh clean all --keep 3
```
