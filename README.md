# Home Manager Config

Nix flakes configuration for Generic Linux and macOS.

## Requirements

Nix installed with flakes enabled.

## Installation

Clone this repository to `~/.nix`:

```bash
git clone <repository-url> ~/.nix
cd ~/.nix
```

## Bootstrap

```bash
nix run home-manager -- switch --flake . -b backup
# Restart your shell to apply changes
```

## Usage

Apply changes:
```bash
nh home switch
```

Update inputs:
```bash
cd ~/.nix
nix flake update
```

Clean old generations:
```bash
nh clean all --keep 3
```
