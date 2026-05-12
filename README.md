# Home Manager Configuration

Nix flakes configuration for Generic Linux and macOS.

## Installation

```bash
git clone <repository-url> ~/.nix
cd ~/.nix

# Bootstrap
make bootstrap
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

### Secrets

Managed via [SOPS](https://github.com/getsops/sops). Personal constants are decrypted at eval-time; application tokens are decrypted at runtime by sops-nix.

```bash
make decrypt          # Decrypt all secrets to JSON for inspection
make encrypt          # Re-encrypt after editing
make edit-personal    # Edit personal constants interactively
make edit-tokens      # Edit application tokens interactively
make clean            # Remove plaintext from disk
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
