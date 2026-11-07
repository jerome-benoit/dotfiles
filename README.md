# Home Manager Configuration

Nix flakes configuration for Generic Linux and macOS.

## Installation

Before bootstrapping, install the configured SOPS age identity outside the repository with permissions `0600`.

```bash
git clone <repository-url> ~/.nix
cd ~/.nix

# Bootstrap
make bootstrap SPEC=work     # or SPEC=personal
```

Restart your shell.

## Usage

### Home Manager

```bash
# Apply changes (preserves current specialisation)
hm

# Switch specialisation (from an active specialisation)
hmw  # work
hmp  # personal

# Or via Makefile
make switch SPEC=work
```

### Private configuration and credentials

Managed via [SOPS](https://github.com/getsops/sops). Private configuration is decrypted at eval-time; runtime credentials are decrypted by sops-nix.

```bash
make decrypt-private  # Decrypt private configuration only for Nix evaluation
make decrypt          # Decrypt private configuration and credentials for inspection
make encrypt          # Re-encrypt private configuration and credentials after editing
make edit-private     # Edit private configuration interactively
make edit-credentials # Edit runtime credentials interactively
make clean            # Remove decrypted private configuration, credentials, and temporary files
```

Interactive SOPS edits replace existing ciphertext only after successful encryption.
Edits use private temporary files, removed after the editor and its supervised processes stop.
Uncatchable termination or machine failure may leave plaintext behind.

### GPG keypair

Subkeys and passphrase are bundled, age-encrypted to the project's age recipient, and committed at `secrets/gpg/keypair.tar.gz.age`. Home-manager activation imports them idempotently on any machine where the configured SOPS age identity is present.

```bash
make encrypt-gpg      # one-shot from a trusted machine; then commit the bundle
```

Recovery: with the configured SOPS age identity + the git repo, SOPS secrets and GPG subkeys are recoverable. The GPG primary key is not in the bundle; back it up separately offline.

GPG bundle exports replace the previous bundle only after successful encryption and verification.
Bundle passphrases preserve leading and trailing whitespace.

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
                     # - Build Home Manager configurations for the current platform
```

Focused integration checks require an `x86_64-linux` builder. They use disposable secrets
and do not activate your environment, download models, or run GPU inference.

```bash
nix build .#checks.x86_64-linux.secrets
nix build .#checks.x86_64-linux.consumers
nix build .#checks.x86_64-linux.hermes-agent
nix build .#checks.x86_64-linux.caveman
```

### Maintenance

```bash
nix flake update     # Update inputs
nh clean all --keep 3 --optimise
```
