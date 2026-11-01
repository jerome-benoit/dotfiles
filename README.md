# Home Manager Configuration

Nix flakes configuration for Generic Linux and macOS.

## Installation

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

# Switch specialisation
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

### GPG keypair

Subkeys and passphrase are bundled, age-encrypted to the project's age recipient, and committed at `secrets/gpg/keypair.tar.gz.age`. Home-manager activation imports them idempotently on any machine where the configured SOPS age identity is present.

```bash
make encrypt-gpg      # one-shot from a trusted machine; then commit the bundle
```

Recovery: with the configured SOPS age identity + the git repo, SOPS secrets and GPG subkeys are recoverable. The GPG primary key is not in the bundle; back it up separately offline.

Secret edits and GPG bundle exports stage ciphertext beside the destination and publish
only after successful completion. Failed writes leave the previous ciphertext intact.
SOPS edits preserve YAML filetype detection in the configured editor.
Interactive SOPS plaintext stays in a private manager-owned workspace, removed after
supervised editor shutdown, including handled hangup and quit signals. Uncatchable
termination or machine failure cannot guarantee plaintext cleanup.
GPG bundle passphrases preserve leading and trailing whitespace.

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

Focused synthetic integration checks (no user activation, real secrets, model downloads or GPU inference):

```bash
nix build .#checks.x86_64-linux.secrets
nix build .#checks.x86_64-linux.consumers
nix build .#checks.x86_64-linux.hermes-agent
nix build .#checks.x86_64-linux.caveman
```

These checks exercise real secret consumers with disposable keys, literal shell
arguments, terminal dispatch, editor APIs, real Pyright initialization and buffer
attachment, and generated agent integrations.
Darwin login ordering still requires native-platform validation.

### Maintenance

```bash
nix flake update     # Update inputs
nh clean all --keep 3
```
